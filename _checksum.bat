@echo off
cl -nologo -MD -Oxb2 -LD -IC:/Python27/include _checksum.c C:/Python27/libs/python27.lib user32.lib /link /out:_checksum.pyd
rem cl -D_DEBUG -GZh -Zi -MDd -LDd -I../include mmap2.c ../libs/python16_d.lib user32.lib penter.lib /link /out:mmap2.pyd
rem cl -GZh -Zi -MDd -LDd -I../include mmap2.c ../libs/python22.lib user32.lib penter.lib /link /out:mmap2.pyd
del _checksum.obj
del _checksum.exp
del _checksum.lib
