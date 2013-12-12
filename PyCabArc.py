#!/usr/bin/python

"""
PyCabArc.py

This Python 2.7 module (and stand-alone mini app) shows how to use zlib module
to emulate "MS"-ZIP compression in a cabinet. It can span cabinet sets, too!


MS-ZIP COMPRESSION EMULATION
============================
A CAB folder's uncompressed stream is processed in 32 KiB blocks (the last
one can be smaller).

Each CAB folder gets a new ZSTREAM, with zlib set to emit raw Deflate blocks.

Each block is then compressed with a Z_SYNC_FLUSH deflate call plus a Z_FINISH
call (from a cloned compressor object) to mark the end of the ZSTREAM: so the
last Deflate sub-block is marked as final but the compression history is saved,
like MS spec formally requires (Cabarc 5.2 and the Windows shell, however, can 
extract a stream built with many Z_SYNC_FLUSH calls and a single Z_FINISH at
folder's end).

Since a raw compressed block MUST never exceed 32768+12 bytes, when such a block
is found, we emit it uncompressed, requiring exactly 32775 bytes ('CK' + block
type 01 + block length 0x8000 + 1 complement 0x7FFF + raw data).

Moreover, it seems that assigning less memory to the zlib deflater (memlevel=6
instead of 8, the default), provides better compression ratio at a reasonable
expense of speed.

The generated cabinet will then be successfully extracted by CABARC and other
tools supporting cabinet files (Windows Shell, extract, WinZip, WinRAR,
cabextract, 7-zip, etc.).

NOTE THAT SOME OF THESE TOOLS *REQUIRE* CFDATA CHECKSUMS TO WORK PROPERLY!

Current version supports having more folders, even with different compression type.
Quantum compression is not supported.

LZX is implemented with the MSCompression library, that actually doesn't work properly.


MODULE USAGE
============
	from PyCabArc import *

	cab = Cabinet('a.cab','w') # an optional 3rd argument sets max cabinet size
	cab.AddHeader()
	cab.AddFolder()
	cab.Add('cabarc.doc')
	cab.AddWild('C:/Windows/INF/*.*')
	cab.AddFolder(0) # specify 0 to store only
	cab.AddWild('C:/My Documents/MP3/*.mp3')
	cab.Flush()
	cab.Close()

Mini app samples:

	PyCabArc.py -P * a.cab /usr/python/lib/*.pyo
	PyCabArc.py -r -m mszip:1 -d 1400000 -l "INF Cabinet #" infcab#.cab c:\windows\inf


HISTORY:
=======
05.11.2004  v0.1     single-pass, single-cabinet creator (w/"MS"-ZIP)
06.11.2004  v0.1...  added command line; experiments with cabinet sets begin
19.11.2004  v0.2     cabinet sets work well (at least, I hope!): temporary files
                     are used to store CFDATAs for each cabinet unit
20.11.2004           some retouch to last version (and recursion added)
21.11.2004  v0.21    introduced new (more efficient) compression technique
22.11.2004  v0.22    a few error checks, and other minor additions
25.11.2004  v0.23    ability to read an external file list
18.07.2005  v0.24    removed bug for compressed blocks > 32780 byte
23.07.2005  v0.25    removed item duplication bug
09.09.2012  v0.26a   LZX experiments with MSCompression.dll
11.09.2012  v0.27a   changed the -m switch for LZX (similar to MS Cabarc)
                     moved to the logging interface for debugging
                     added compression levels to -m mszip:1..9
                     added elapsed seconds to statistics
12.09.2012  v0.28a   if a folder is on the cmdline, adds its files in non-recursive mode
                     gracefully exits if there aren't files to add
                     it won't try anymore to compress 0 length input, nor to write zero CFDATA
                     no more division by 0 error for empty CAB in stats
15.09.2012  v0.29    encodes items to UTF-8 as needed
                     gets DOS file perms in Win32
                     hidden -D switch to explicitly turn DEBUG log on
                     average speed in stats
29.10.2012  v.0.30   finally fixed a severe bug with MS-ZIP blocks >32780 bytes
                     converted to dumb add mode (permit duplicated items)
                     reverted zlib to a faster approach in time/ratio/mem balancing
01.11.2012  v.0.31   implemented checksum algorithm in pure Python (w/ ctypes)
08.01.2013  v.0.32   fixed import of Checksum function
                     implemented an LZX2 class with Jeff's CabLzxDll
11.12.2013  v.0.33   works again with -m NONE
                     always marks last CFDATA Deflated sub-block as final


TO DO & WISHES:
==============
- note: using Python ctypes and logging breaks compatibility with older Pythons
- integrate FileSetStream in I/O?
- add references to container in each object (to simplify things)?
- bind compressor object to its folder (so each folder gets its own compression
  method and/or level? is this permitted?
- add a simple extractor?
- split, merge and update cabinets (all require folder recompression ;-)
- better error checking
- limit folders by size?
- update cmd line manager with optparse/argparse?
- find infos about 3DES encrypted CABs? Windows Phone?

WARNING: according to VS2010 documentation, a splitted CAB couldn't contain more than
15 files across 2 segments... Did such limit exist with those old Win95 MSDMF CABs???
"""

VERSION = '0.33'

COPYRIGHT = '''Copyright (C)2004-2013, by maxpat78. GNU GPL v2 applies.
This free software creates MS Cabinets WITH ABSOLUTELY NO WARRANTY!'''

DEBUG = 0

import fnmatch
import getopt
import glob
import logging
import os
import random
import struct
import sys
import tempfile
import time
import zlib
from ctypes import *
from datetime import datetime as dt

def Checksum(s, seed=0):
	"Implements MS CAB xoring checksum in Python (~33% slower than C version)"
	csum = seed
	loops = len(s) / 8
	i = 0
	while loops > 0:
		csum ^= cast(s[i:i+8], POINTER(c_ulonglong)).contents.value
		i += 8
		loops -= 1
	rem = len(s) % 8
	if rem:
		if rem >= 4:
			csum ^= cast(s[i:i+4], POINTER(c_ulong)).contents.value
			i += 4
		j = rem % 4
		while j:
			j -= 1
			csum ^= (cast(s[i], POINTER(c_ubyte)).contents.value << j*8)
			i += 1
	return abs((csum & 0xFFFFFFFF) ^ (csum >> 32))

try:
	# Optional Python module... what a difficult thing to implement!!!
	import _checksum
	CKS = _checksum.checksum
except:
	CKS = Checksum

class idict(dict):
	"Dictionary with case-insensitive (or wildcarded) keys"
	def __contains__ (p, item):
		if dict.__contains__(p,item) or fnmatch.filter(dict.keys(p),item):
			return 1
		return 0

	def __getitem__ (p, key):
		if not dict.has_key(p,key):
			try:
				key = fnmatch.filter(dict.keys(p),key)[0]
			except:
				pass
		return dict.__getitem__(p,key)

	def __setitem__ (p, key, value):
		try:
			key = fnmatch.filter(dict.keys(p),key)[0]
		except:
			pass
		return dict.__setitem__(p,key,value)

class LZX:
# Emulates an LZX compressor by directly accessing Jeff's MSCompression.dll
	def __init__(p, level=15):
		p.level = level
		p.state = cdll.MSCompression.lzx_cab_compress_start(level)
		
	def compress(p, s):
		if not s: return ''
		SIZE_T=32768+6144
		dst = create_string_buffer(SIZE_T)
		size = cdll.MSCompression.lzx_cab_compress_block(s, len(s), dst, SIZE_T, p.state)
		logging.debug('lzx_cab_compress_block 2^%d returned %d from %d bytes', p.level, size, len(s))
		return dst[:size]
		
	def flush(p):
		cdll.MSCompression.lzx_cab_compress_end(p.state)
		p.state = cdll.MSCompression.lzx_cab_compress_start(p.level)
		return ''

class LZX2:
# Emulates an LZX compressor by directly accessing Jeff's CabLzxDll.dll
	def __init__(p, level=15):
		p.level = level
		cdll.CabLzxDll.fci_init()
		
	def compress(p, s):
		if not s: return ''
		SIZE_T=32768+6144
		dst = create_string_buffer(SIZE_T)
		size = cdll.CabLzxDll.fci_lzx_cab_compress(s, len(s), dst, SIZE_T, p.level, 1)
		logging.debug('fci_lzx_cab_compress 2^%d returned %d from %d bytes', p.level, size, len(s))
		return dst[:size]
		
	def flush(p):
		cdll.CabLzxDll.fci_init()
		return ''

class MSZIP:
# Emulates (more efficiently) a "MS"-ZIP compressor using ZLIB
	def __init__(p, level=6, mem=8):
		p.level = level
		p.mem = mem
		# level=1..9, method=8 (DEFLATE), window=2^15,raw(-),
		# mem=6, data type=0 (unknown)
		p.obj = zlib.compressobj(level, 8, -15, mem, 0)
		
	def compress(p, s):
		"Compresses a string, and eventually discards superflous bytes"
		buf = p.obj.compress(s)
		buf = 'CK' + buf + p.obj.flush(zlib.Z_SYNC_FLUSH) + p.obj.copy().flush(zlib.Z_FINISH)
		if len(buf) > 32780:
			logging.debug("Got %d bytes compressed: emitting uncompressed block", len(buf))
			# CK + 01 + 0x8000 + 0x7FFF + 32KiB raw data
			buf = '\x43\x4B\x01\x00\x80\xFF\x7F' + s
		return buf
		
	def flush(p):
		"Flushes last folder, and creates a new compressor for the next one"
		p.obj = zlib.compressobj(p.level, 8, -15, p.mem, 0)
		return ''


def info(s):
	"Prints stuff when operating in application mode"
	if __name__ != '__main__': return
	print s


def fmtn(n):
	"Beautify & stringify big integers"
	L = list(str(n))
	l = len(L)
	for i in range(-3,-l,-3):
		L.insert(i+l,',')
	return ''.join(L)


def Disk2CabName(name, strip=''):
# Makes a CAB item name from a pathname
# WARNING: item name must be <256 bytes (with end NULL)!
# Memento! strip argument must contain a name with back slashes only ( \ )
# WARNING: 16-bit DOS tools don't like pathnames > 32 chars!
	name = os.path.splitdrive(name)[1]
	name = name.replace('/','\\')
	if name[0] == '\\':
		name = name[1:]
	if strip and strip == '*':
		name = name[1+name.rfind('\\'):]
	elif strip:
		name = name.replace(strip,'')
	return name

	
class CFDATA:
# Cabinet Data block
	def __init__(p, data='', udata=0, cdata=0):
		p.format = '<L2H' # 8 bytes
		p.data = data
		p.cbData = cdata # length of compressed data in this record
		p.cbUncomp = udata # length of uncompressed data (or 0 if it continues)
		p.csum = 0 # checksum: may be omitted (better not)
		p.abReserve = '' # not used (yet)
		
	def size(p): return 8 + p.cbData
	
	def isempty(p): return (p.cbData == 0)
	
	def Read(p, fp, data=0):
		pos = fp.tell()
		s = fp.read(8)
		if len(s) < 8:
			p.csum, p.cbData, p.cbUncomp = 0, 0, 0
			return 0
		s = struct.unpack(p.format,s)
		p.csum, p.cbData, p.cbUncomp = s
		if data:
			p.data = fp.read(p.cbData)
		else:
			p.data = ''
			fp.seek(p.cbData,1)
		logging.debug('Read CFDATA @0x%08X: 0x%08X bytes (0x%08X bytes), csum=0x%08X', pos, p.cbData, p.cbUncomp, p.csum)
		return 1
		
	def Write(p, fp, data=0):
		pos = fp.tell()
		if not p.cbData:
			logging.debug('Discarded empty CFDATA @0x%08X', pos)
			return 1
		s = struct.pack(p.format, p.csum, p.cbData, p.cbUncomp)
		if CKS:
			p.csum = CKS(p.data[:p.cbData])
			p.csum = CKS(s[4:],p.csum)
		s = struct.pack(p.format, p.csum, p.cbData, p.cbUncomp)
		fp.write(s)
		if data:
			fp.write(p.data[:p.cbData])
		logging.debug('Written CFDATA @0x%08X: 0x%08X bytes (0x%08X bytes), csum=0x%08X', pos, p.cbData, p.cbUncomp, p.csum)
		return 1


class CFFILE:
# Internal Cabinet File structure
	def __init__(p):
		p.format = '<2L4H' # 16 bytes + sizeof(name) + NULL
		p.cbFile = 0 # uncompressed file size
		p.uoffFolderStart = 0 # uncompressed file offset in its folder
		p.iFolder = 0 # index of folder container
				# (0xFFFD=prev 0xFFFE=next 0xFFFF=prev & next)
		p.date = 0 # FAT-style date, time, attributes
		p.time = 0
		p.attrs = 0x20 # 0x01 R  0x02 H  0x04 S  0x20 A  0x40 to exec  0x80 UTF
		p.Name = '' # item name (max 255?)
		p.path = '' # source file pathname
		
	def size(p): return 16+len(p.Name)+1
	
	def _adjust(p):
		p.cbFile = os.stat(p.path)[6]
		x = time.localtime(os.stat(p.path)[8])[0:6]
		p.date = (x[0] - 1980) << 9 | x[1] << 5 | x[2]
		p.time = x[3] << 11 | x[4] << 5 | x[5] >> 1
		
	def Read(p, fp):
		s = fp.read(16)
		s = struct.unpack(p.format,s)
		(p.cbFile, p.uoffFolderStart, p.iFolder, p.date, p.time, p.attrs) = s
		s = fp.read(1)
		while s != '\x00':
			p.Name += s
			s = fp.read(1)
		logging.debug('Read CFFILE=%s, size=%d, off=%d, ind=%d', p.Name, p.cbFile, p.uoffFolderStart, p.iFolder)
			
	def Write(p, fp):
		s = struct.pack(p.format, p.cbFile, p.uoffFolderStart, p.iFolder, p.date, p.time, p.attrs)
		fp.write(s)
		fp.write(p.Name+'\x00')
		

class IOStream:
# Helps transforming a continuous (per-folder) 32K input stream into a per-cabinet
# (eventually compressed) CFDATA output stream...
	def __init__(p, cabset, compression):
		p.C = cabset
		if 0 < compression < 10:
			p.CPR = MSZIP(compression) # default compressor
			logging.debug("Set MSZIP compressor with level %d", p.CPR.level)
		elif (compression & 0xFF) == 3:
			p.CPR = LZX(compression >> 8)
			logging.debug("Set LZX compressor with level %d", p.CPR.level)
		else:
			logging.debug("Set NONE compressor")
		p.fin = 0 # file actually read
		p.fout = [tempfile.TemporaryFile()] # temp files
		p._files = [] # files to process
		p._file = 0 # CFFILE worked on
		p.limit = p.C.limit
		p.buf = '' # data buffer
		p.ulen, p.clen = 0, 0
		p.opened = [] # files across cabinets
		p._flushing = 0 # close folder ASAP flag
		p.c1, p.c2 = 0, 0 # total bytes read, written
		p.c3, p.c4 = 0, 0 # total files opened, cabinets written
		
	def _open(p):
		if p.fin:
			p.fin.close()
			p.fin = 0
		if p._flushing:
# In a cabinet set, a folder (and, so, its last file) is closed as soon as
# the maximum cabinet unit size has been reached
			p._flushing = 0
			p.C._addfolder(p.C.ch[-1].Folders[-1].typeCompress)
		if not p._files: return 0
		p._file = p._files.pop(0)
		info('  adding: '+p._file.Name)
		try:
			p._file._adjust()
			p.fin = file(p._file.path,'rb')
		except:
			info('WARNING! file %s skipped!'%(p._file.path))
			return 0
		P = p.C.ch[-1].Folders
		p._file.iFolder = len(P) - 1
		p._file.uoffFolderStart = P[-1].Size
		P[-1].Size += p._file.cbFile
		P[-1].Files += [p._file]
		p.c3 += 1
		return 1
		
	def _cabsize(p): return p.fout[-1].tell() + p.C.ch[-1].size()
	
	def _cabisfull(p): return (p._cabsize() >= p.limit)
	
	def _read(p, n=32768):
		if not p.fin and not p._open():
			return 0
		n -= len(p.buf)
		s = p.fin.read(n)
		x = len(s)
		if not x:
			p.fin.close()
			p.fin = 0
			return 0
		p.buf += s
		p.c1 += x
		logging.debug('Buffer: %d/32768 (wanted %d, read %d from %s)', len(p.buf), n, x, p._file.path)
		if len(p.buf) < 32768:
			p.fin = 0
			if p._cabisfull() or p._flushing:
				return 0
			return p._read(n-x)
		return 1
		
	def _filter(p, flush):
		p.clen = p.ulen = len(p.buf)
		if p.C.ch[-1].Folders[-1].typeCompress and p.ulen: # try to compress only if not zero
			p.buf = p.CPR.compress(p.buf)
			if flush:
				p.buf += p.CPR.flush()
			p.clen = len(p.buf)
		p.c2 += p.clen
		
	def _copycab(p, last=0):
		logging.debug('Flushing cabinet #%d...', p.C.Index)
		info('Flushing cabinet #%d...'%(p.C.Index))
		X = p.C.ch[-1].Folders[-1]
# Properly set iFolder member for CFFILEs
		for x in X.Files:
			if x.uoffFolderStart >= (X.cCFData-1)*32768 or \
				  x.uoffFolderStart + x.cbFile >= (X.cCFData-1)*32768:
				if x.iFolder in [0xFFFD, 0xFFFF]:
					if last:
						x.iFolder = 0xFFFD
					else:
						x.iFolder = 0xFFFF
				else:
					if not last:
						x.iFolder = 0xFFFE
				p.opened += [x]
		f = file(p.C.lastname,'wb')
		p.C.ch[-1].Write(f)
		for x in p.opened:
			if x.iFolder in [0xFFFE,0xFFFF]:
				x.iFolder = 0xFFFD
		c = CFDATA()
		while c.Read(p.fout[-1],1):
			c.Write(f,1)
		p.fout[-1].close() # discard temp file
		p.c4 += 1
		
	def _write(p, end):
		if not end and len(p.buf) < 32768:
			return 0
		p._filter(end)
		s = p.buf
		p.buf = ''
		x = CFDATA(s,p.ulen,p.clen)
		logging.debug('actual CAB sizes: %d -> %d bytes', p._cabsize(), p._cabsize()+x.size())
		p.C.ch[-1].Folders[-1].cCFData += 1
		if p._cabsize() + x.size() < p.limit:
			x.Write(p.fout[-1],1)
			return 1
		x.cbUncomp = 0
		x.cbData = p.limit - p._cabsize() - 8
		x.Write(p.fout[-1],1) # Write part
		p.fout[-1].seek(0)
		p._copycab()
		x = CFDATA(s[x.cbData:],p.ulen,p.clen-x.cbData)
		p.fout += [tempfile.TemporaryFile()]
		t = p.C.ch[-1].Folders[-1].typeCompress
		p.C.AddHeader()
# The 1st folder contains only residual data...
		p.C._addfolder(t)
		p.C.ch[-1].Folders[-1].cCFData += 1
		p.C.ch[-1].Folders[-1].Files += p.opened
		x.Write(p.fout[-1],1) # Write residual bytes
		p.opened = []
		p._flushing = 1 # signal to close folder

	def push(p, item):
		p._files += [item]

	def flush(p, end=0):
		while p._read():
			p._write(end)
		p._write(p._flushing | end)


class CFFOLDER:
# Internal Cabinet Folder structure
	def __init__(p):
		p.format = '<L2H' # 8 bytes
		p.coffCabStart = 0 # 1st CFDATA offset for this folder
		p.cCFData = 0 # folder's CFDATA in this cabinet
		p.typeCompress = 0 # 0=none 1="MS"-ZIP 2=QUANTUM 0xNN03=LZX with window size 2^NN
		p.Files = []
		p.Size = 0
		p.abReserve = '' # not used (yet: why doesn't MS put an AES-key here...?)
		
	def size(p):
		x = 8
		for o in p.Files:
			x += o.size()
		return x
		
	def Read(p, fp):
		s = fp.read(8)
		s = struct.unpack(p.format,s)
		(p.coffCabStart, p.cCFData, p.typeCompress) = s
		logging.debug('Read CFFOLDER=%d, blocks=%d, comp=%d', p.coffCabStart, p.cCFData, p.typeCompress)
			
	def Write(p, fp):
		if 1 < p.typeCompress < 10:
			p.typeCompress = 1 # MSZIP Level to Flag
		s = struct.pack(p.format, p.coffCabStart, p.cCFData, p.typeCompress)
		fp.write(s)


class CFHEADER:
# Initial Cabinet Header structure
	def __init__(p):
		p.format = '<4s5l2B5H' # 36 bytes
		p.signature = 'MSCF'
		p.reserved1 = 0
		p.cbCabinet = 0 # cabinet size
		p.reserved2 = 0
		p.coffFiles = 0 # 1st CFFILE offset
		p.reserved3 = 0
		p.versionMinor = 3
		p.versionMajor = 1
		p.cFolders = 0 # folders in cabinet
		p.cFiles = 0 # files in cabinet
		p.flags = 0 # 0x1 has prev, 0x2 has next, 0x4 reserved fields set
		p.setID = random.randint(1,65536) # I prefer a random ID...
		p.iCabinet = 0 # cabinet index in a set
		p.cbCFHeader = 0 # optional size of per-cabinet reserved area (upto 60.000 bytes)
		p.cbCFFolder = 0 # optional size of per-folder reserved area (upto 255 bytes)
		p.cbCFData = 0 # optional size of per-datablock reserved area (upto 255 bytes)
		p.abReserve = '' # per-cabinet reserved area
		p.szCabinetPrev = '\x00' # max 255 bytes for all, plus NULL
		p.szDiskPrev = '\x00'
		p.szCabinetNext = '\x00'
		p.szDiskNext = '\x00'
		p.Folders = []
		p.IO = 0
		
	def size(p): return p.size1() + p.size2()
	
	def size1(p):
		x = 36
		if p.flags & 0x1:
			x += len(p.szCabinetPrev) + len(p.szDiskPrev)
		if p.flags & 0x2:
			x += len(p.szCabinetNext) + len(p.szDiskNext)
		if p.flags & 0x4:
			x += 4 + p.cbCFHeader
		return x
		
	def size2(p):
		x = 0
		for o in p.Folders:
			x += o.size()
		return x
		
	def _adjust(p):
		p.cFiles = 0
		p.cFolders = len(p.Folders)
		for fol in p.Folders:
			p.cFiles += len(fol.Files)
			
	def Read(p, fp):
		s = fp.read(36)
		s = struct.unpack(p.format,s)
		(p.signature, p.reserved1, p.cbCabinet, p.reserved2, p.coffFiles, p.reserved3, p.versionMinor, p.versionMajor,
		p.cFolders, p.cFiles, p.flags, p.setID, p.iCabinet) = s
		assert (p.signature == 'MSCF')
		logging.debug('Read CFHEADER=%d bytes, off=%d', p.cbCabinet, p.coffFiles)
		for n in xrange(p.cFolders):
			cf = CFFOLDER()
			cf.Read(fp)
			p.Folders += [cf]
		for n in xrange(p.cFiles):
			cf = CFFILE()
			cf.Read(fp)
			p.Folders[cf.iFolder].Files += [cf]
			
	def Write(p, fp, again=0):
		p._adjust()
		fp.seek(0)
		s = struct.pack(p.format,p.signature, p.reserved1, p.cbCabinet, p.reserved2, p.coffFiles, p.reserved3,
		p.versionMinor, p.versionMajor, p.cFolders, p.cFiles, p.flags, p.setID, p.iCabinet)
		fp.write(s)
		if p.flags & 0x4:
			s = struct.pack('<1H2B',p.cbCFHeader,p.cbCFFolder,p.cbCFData)
			fp.write(s)
			fp.write(p.abReserve)
		if p.flags & 0x1:
			fp.write(p.szCabinetPrev+p.szDiskPrev)
		if p.flags & 0x2:
			fp.write(p.szCabinetNext+p.szDiskNext)
		for o in p.Folders:
			o.Write(fp)
		p.coffFiles = fp.tell()
		for o in p.Folders:
			o.coffCabStart = o._coffCabStart + p.size()
			for o1 in o.Files:
				o1.Write(fp)
		if not again:
			p.Write(fp,1) # rewrites with updated coffFiles


class Cabinet:
# Class to manage a single Cabinet, or a set
	def __init__(p, name, mode, limit=2**32, compression=0):
		p.Index = 0 # set index
		p.destname = name # cabinet name or cabinet set root name
		p.lastname = p._name(name) # file to write to
		p.label = '' # disk label for a set
		p.reserved = 0 # per-header reserved space
		p.limit = limit # CAB unit max size - default: 4 GiB (required to let other things work properly)
		p.ch = [] # cabinet headers
		p.IO = IOStream(p, compression) # I/O stuff helper
		p.idict = idict() # CFFILEs dictionary
		if limit < 50000:
			raise 'CabArcException', 'Microsoft wants a cabinet unit size greater than 50.000 bytes!'
		if mode == 'r':
			p.f = file(name,mode+'b')
			p.AddHeader()
			p.ch[-1].Read(p.f)
		elif mode == 'w':
			pass # eh! eh! eh!
		else:
			raise 'CabArcException', "You MUST specify 'r' or 'w' as Cabinet open mode!"
			
	def _name(p, s, type=1):
		"Generates a disk (or label) name for current (default), previous or next cabinet unit"
		i = p.Index
		if type == 0: i -= 1
		if type == 2: i += 1
		s = s.replace('#',str(i))
		return s
		
	def _additem(p, itemname, pathname, dt=None):
		"Adds a disk file to the last folder with the specified internal name (and date)"
		if not p.ch:
			raise 'CabArcException', 'You MUST add a Cabinet header before adding folders!'
		if not p.ch[-1].Folders:
			raise 'CabArcException', 'You MUST add a Cabinet folder before adding files!'
		if not p.IO:
			raise 'CabArcException', "You CAN'T add files to a closed Cabinet!"
		#~ if itemname in p.idict:
			#~ info("WARNING: skipping '%s' because it is already archived!" % itemname)
			#~ return
		f = CFFILE()
		f.path = pathname
		f.Name = itemname
		try:
			f.Name.encode('cp850')
		except UnicodeEncodeError:
			f.Name = f.Name.encode('utf8')
			f.attrs |= 0x80
		if len(f.Name) > 255: # with UTF-8, too?
			info("WARNING: '%s' item name > 255 chars, skipped!" % itemname)
			return
		if not os.access(pathname,os.W_OK):
			f.attrs |= 0x1
		if sys.platform in ('win32', 'cygwin'):
			attrs = windll.kernel32.GetFileAttributesA(pathname)
			if attrs & 0x2: f.attrs |= 0x2
			if attrs & 0x4: f.attrs |= 0x4
			if attrs & 0x20: f.attrs |= 0x20
			logging.debug('Extracted DOS perms: %08X', f.attrs)
		logging.debug('Pushed file %s', pathname)
		p.idict[itemname] = f
		p.IO.push(f)
		p.IO.flush()

# High-level, quasi-external functions
	def AddHeader(p):
		"Adds an header to current cabinet. One header IS REQUIRED to add folders!"
		p.Index += 1
		p.lastname = p._name(p.destname)
		p.ch += [CFHEADER()]
		P = p.ch[-1]
		P.IO = p.IO
		if p.reserved:
			P.flags |= 0x4
			P.cbCFHeader = p.reserved
			P.abReserve = P.cbCFHeader * '\x00'
		if p.limit:
			dn = os.path.split(p.destname)[1]
			P.cbCabinet = p.limit
			P.flags |= 0x2
			P.szCabinetNext = p._name(dn,2)+'\x00'
			if p.label:
				P.szDiskNext = p._name(p.label,2)+'\x00'
			if len(p.ch) > 1:
				P.flags |= 0x1
				P.setID = p.ch[-2].setID
				P.iCabinet = p.ch[-2].iCabinet + 1
				P.szCabinetPrev = p._name(dn,0)+'\x00'
				if p.label:
					P.szDiskPrev = p._name(p.label,0)+'\x00'

	def _addfolder(p, type=1):
		f = CFFOLDER()
		f._coffCabStart = p.IO.fout[-1].tell() # relative offset
		f.typeCompress = type
		p.ch[-1].Folders += [f]
		p.ch[-1].cFolders += 1

	def AddFolder(p, type=1):
		"Adds a folder to the cabinet. At least 1 folder IS REQUIRED to add files!"
		if not p.ch:
			raise 'CabArcException', 'You MUST add a Cabinet header before adding folders!'
		if p.ch[-1].Folders:
			p.IO.flush(1) # flush any previous open folder
		# Type may be: 0 (uncompressed), 1..9 (MSZIP with level 1..9),
		# 0x0F03..0x1503 (LZX with dictionary 15..21)
		p._addfolder(type)

	def Add(p, name, strip=''):
		"Adds a disk file to the last folder"
		if name == '+':
			return p.AddFolder()
		p._additem(Disk2CabName(name,strip),name)

	def AddWild(p, name, strip=''):
		"Adds a disk file to the last folder, with complex wildcard support"
		# i.e. cab.AddWild('C:\TEMP\???\*.txt')
		if name == '+':
			return p.AddFolder()
		for o in glob.glob(name):
			p._additem(Disk2CabName(o,strip),o)

	def Flush(p):
		"Flush all structures and folders data to disk"
		if not p.ch or not p.ch[-1].Folders:
			raise 'CabArcException', "You CAN'T flush a Cabinet without headers, folders or files!"
		p.IO.flush(1)
		p.ch[-1].flags ^= 0x2
		p.ch[-1].cbCabinet = p.IO.fout[-1].tell() + p.ch[-1].size()
		p.IO.fout[-1].seek(0)
		p.IO._copycab(1)

	def Close(p):
		p.IO = 0

	def Stats(p):
		"Returns a tuple with total bytes read and written, files opened, cabinets written and compression ratio"
		if p.IO:
			return ( p.IO.c1, p.IO.c2, p.IO.c3, p.IO.c4, float(p.IO.c2)/float(p.IO.c1) )
		else:
			return (0,0,0,0,0)



def cmdparse():
	print "PyCabArc.py - Version "+VERSION+"\n"+COPYRIGHT+"\n"
	strip, comp, limit, res, rec, label = '', 9, 2**32, 0, 0, ''
	opts, args = getopt.getopt(sys.argv[1:], 'Dd:hi:l:m:P:rs:')

	for opt, arg in opts:
		if opt == '-h':
			print '''Usage: PyCabArc [options] file.cab files

Options:
-i file   picks a list of file to compress from 'file'
-r        searches for files in each sub-directory, too
-P str    strips str from item path (* = all)
-m        sets compression type [NONE|MSZIP:1..9(default)|LZX:15..21]
-s n      reserves n bytes in the cabinet header (max 60,000)
-d size   limits each cabinet unit in a set to size (at least 50,000 bytes)
          (use # in cabinet name to replace with progressive index)
-l label  specifies a user-friendly disk label for each cabinet unit in a set
	  (use # to replace with progressive index)

File names can contain complex wildcards (ex. /usr/python/li*/*.pyc);
directory names in recursive mode can not.
	
Use a plus sign (+) as file name to force adding a new folder.
	
MSZIP compression level can be set between 1 and 9 (default).
LZX dictionary size can be set between 15 (32 KiB) and 21 (2 MiB).'''
			sys.exit(-1)

		def parse_complevel(s):
			if ':' in s:
				x = s.split(':')[1] or '0'
				return int(x)
			else:
				return 0

		if opt == '-P':	strip = arg
		if opt == '-m':
			arg = arg.lower()
			if arg == 'none':
				comp = 0
			elif 'mszip' in arg:
				comp = parse_complevel(arg) or 6
				if comp < 1 or comp > 9:
					print "Bad compression level for MSZIP: MUST be in the range 1...9!"
					sys.exit(-2)
			elif 'lzx' in arg:
				comp = parse_complevel(arg) or 15
				if comp < 15 or comp > 21:
					print "Bad compression level for LZX: MUST be in the range 15...21!"
					sys.exit(-2)
				comp = 3 | (comp << 8)
			else:
				print "Bad compression method with -m!"
				sys.exit(-2)
		if opt == '-d':	limit = int(arg)
		if opt == '-D':
			logging.basicConfig(level=logging.DEBUG, filename='PyCabArc.py.log', filemode='w')
		if opt == '-s':	res = int(arg)
		if opt == '-r':	rec = 1
		if opt == '-l':	label = arg
		if opt == '-i':
			print 'Reading files list from', arg
			for li in file(arg).readlines():
				args += [li[:-1]]
		
	if len(args) < 2:
		print 'Few arguments! Use -h switch to learn more...'
		sys.exit(-3)

	if res > 60000:
		print "You can't reserve more than 60,000 bytes in CAB header!"
		sys.exit(-4)

	StartTime = dt.now()
	
	cab = Cabinet(args[0], 'w', limit, comp)
	cab.label = label
	cab.reserved = res

	cab.AddHeader()
	cab.AddFolder(comp)

	print "Please wait! Scanning files to add....."
	
	if not rec:
		for arg in args[1:]:
			arg = os.path.expandvars(arg)
			if os.path.isdir(arg):
				arg = os.path.join(arg, '*')
			cab.AddWild(arg,strip)
	else:
		from os.path import join
		for arg in args[1:]:
			arg = os.path.expandvars(arg)
			for root, dirs, files in os.walk(arg, topdown=False):
				for name in files:
					cab.Add(join(root, name),strip)

	if not cab.idict:
		print "No files to add. Exiting..."
		sys.exit(-4)
		
	cab.Flush()

	StopTime = dt.now()
	secs = (StopTime-StartTime).seconds

	x = cab.IO
	y = (cab.Index - 1) * limit + cab.ch[-1].cbCabinet

	print '''

Statistics:
-----------
%s bytes read from %s file(s);
%s (%s) bytes emitted in %d cabinet(s).
Ratio: %f:1. %d seconds elapsed, speed %f KiB/s.
''' % ( fmtn(x.c1), fmtn(x.c3), fmtn(x.c2), fmtn(y), cab.Index, float(x.c2)/(float(x.c1) or 1), secs, x.c1/1024.0/(secs or 1) )

	cab.Close()



if __name__=='__main__':
	cmdparse()
