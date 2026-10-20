# SPDX-License-Identifier: GPL-3.0-or-later
"""Read Windows file/product version strings from the actual executable resource."""
import argparse
import ctypes as C
from ctypes import wintypes as W
from pathlib import Path


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('exe',type=Path)
    parser.add_argument('--version',required=True)
    args=parser.parse_args()
    dll=C.WinDLL('version',use_last_error=True)
    size=dll.GetFileVersionInfoSizeW
    size.argtypes=[W.LPCWSTR,C.POINTER(W.DWORD)];size.restype=W.DWORD
    read=dll.GetFileVersionInfoW
    read.argtypes=[W.LPCWSTR,W.DWORD,W.DWORD,C.c_void_p];read.restype=W.BOOL
    query=dll.VerQueryValueW
    query.argtypes=[C.c_void_p,W.LPCWSTR,C.POINTER(C.c_void_p),C.POINTER(W.UINT)];query.restype=W.BOOL
    length=size(str(args.exe.resolve()),None)
    if not length:raise C.WinError(C.get_last_error())
    buffer=C.create_string_buffer(length)
    if not read(str(args.exe.resolve()),0,length,buffer):raise C.WinError(C.get_last_error())
    for name in ['FileVersion','ProductVersion']:
        pointer=C.c_void_p();count=W.UINT()
        if not query(buffer,'\\StringFileInfo\\040904b0\\'+name,C.byref(pointer),C.byref(count)):raise C.WinError(C.get_last_error())
        actual=C.wstring_at(pointer.value).rstrip('\0')
        if actual!=args.version:raise ValueError(f'{name} {actual!r} != {args.version!r}')
    print('VERSION_METADATA_PASS')


if __name__=='__main__':main()
