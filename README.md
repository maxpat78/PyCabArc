PyCabArc.py
===========

This Python 2.7 module (and stand-alone mini app) shows how to use zlib module
to emulate "MS"-ZIP compression in a cabinet. It can span cabinet sets, too!

Actually, a cabinet extractor is not implemented: but take a look at my CabArk
C# project.


FOLDER CONTENTS
===============

- PyCabArc.py			the main Python module (rev. 0.31)
- _checksum.c			source for a PYD providing cabinet checksum calculation
- _checksum.bat			simple batch to build the PYD with Visual C++
- README.MD				this file
- gpl.txt				GPL v2 license file: it applies to this package


MS-ZIP COMPRESSION IMPLEMENTATION
=================================

A CAB folder's uncompressed stream is processed in 32 KiB blocks (the last
one can be smaller).

Each CAB folder gets a new ZSTREAM, with zlib set to emit raw Deflate blocks.

Each block is then compressed with a Z_SYNC_FLUSH deflate call, the last one
with a Z_FINISH call to mark the end of ZSTREAM.

Since a raw compressed block MUST never exceed 32768+12 bytes according to MS spec,
when such a block is found, we emit it uncompressed, requiring exactly 32775
bytes ('CK' + block type 01 + block length 0x8000 + 1 complement 0x7FFF + raw data).

Actually, 7-Zip (http://www.7-zip.org) can expand a CAB even if it contains
blocks >32780 bytes and the last one isn't marked as final: but MS CABARC 5.2 fails!

Moreover, it seems that assigning less memory to the zlib deflater (memlevel=6 instead
of 8, the default), provides better compression ratio at a reasonable expense of speed.

This method gives a compression ratio slightly superior to CABARC.

The generated cabinet will then be successfully extracted by CABARC and other tools
supporting cabinet files (extract, WinZip, WinRAR, cabextract, 7-zip, ecc.).

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

- 05.11.2004  v0.1     single-pass, single-cabinet creator (w/"MS"-ZIP)
- 06.11.2004  v0.1...  added command line; experiments with cabinet sets begin
- 19.11.2004  v0.2     cabinet sets work well (at least, I hope!): temporary files
                     are used to store CFDATAs for each cabinet unit
- 20.11.2004           some retouch to last version (and recursion added)
- 21.11.2004  v0.21    introduced new (more efficient) compression technique
- 22.11.2004  v0.22    a few error checks, and other minor additions
- 25.11.2004  v0.23    ability to read an external file list
- 18.07.2005  v0.24    removed bug for compressed blocks > 32780 byte
- 23.07.2005  v0.25    removed item duplication bug
- 09.09.2012  v0.26a   LZX experiments with MSCompression.dll
- 11.09.2012  v0.27a   changed the -m switch for LZX (similar to MS Cabarc)
                     moved to the logging interface for debugging
                     added compression levels to -m mszip:1..9
                     added elapsed seconds to statistics
- 12.09.2012  v0.28a   if a folder is on the cmdline, adds its files in non-recursive mode
                     gracefully exits if there aren't files to add
                     it won't try anymore to compress 0 length input, nor to write zero CFDATA
                     no more division by 0 error for empty CAB in stats
- 15.09.2012  v0.29    encodes items to UTF-8 as needed
                     gets DOS file perms in Win32
                     hidden -D switch to explicitly turn DEBUG log on
                     average speed in stats
- 29.10.2012  v.0.30   finally fixed a severe bug with MS-ZIP blocks >32780 bytes
                     converted to dumb add mode (permit duplicated items)
                     reverted zlib to a faster approach in time/ratio/mem balancing
- 01.11.2012  v.0.31   implemented checksum algorithm in pure Python (w/ ctypes)
- 19.11.2012           fixed declaration of Checksum in the script body


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
- port checksum code in pure Python?
- update cmd line manager with optparse/argparse?
- find infos about 3DES encrypted CABs? Windows Phone?

WARNING: according to VS2010 documentation, a splitted CAB couldn't contain more than
15 files across 2 segments... Did such limit exist with those old Win95 MSDMF CABs???
