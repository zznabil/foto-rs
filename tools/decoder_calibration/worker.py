# SPDX-License-Identifier: GPL-3.0-or-later
"""Bounded decoder child with complete payload and argument evidence."""
if not __debug__:
    raise RuntimeError("decoder calibration refuses optimized Python")
import hashlib
import json
import os
from pathlib import Path
import subprocess
import threading
import stress_test as t
from .protocol import header


def sample(exe,image,output,capture=None):
    output.mkdir();exe=exe.resolve();image_text=os.fspath(image)
    assert isinstance(image_text,str),'image argument must be text for exact UTF-16 preservation'
    image_path=Path(image_text)
    argument_utf16_hex=image_text.encode('utf-16le',errors='surrogatepass').hex()
    argument_utf16_units=len(argument_utf16_hex)//4
    r={'exe':str(exe),'exe_sha256':hashlib.sha256(exe.read_bytes()).hexdigest(),'input':image_text,'input_sha256':hashlib.sha256(image_path.read_bytes()).hexdigest(),'input_argument_utf16_units':argument_utf16_units,'input_argument_utf16_hex':argument_utf16_hex,'harness_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'context':'desktop decoder-only, no HWND/presentation','verdict':'INCOMPLETE'}
    process=subprocess.Popen([str(exe),image_text],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,creationflags=subprocess.CREATE_NO_WINDOW)
    r['child_pid']=process.pid
    readers=[];raw=None;box=[];errors=[]
    primary_error=None
    def read_header():box.append(process.stdout.readline())
    try:
        thread=threading.Thread(target=read_header,daemon=True);readers.append(thread);thread.start();thread.join(20)
        assert not thread.is_alive(),'decode exceeded20s measurement budget'
        r.update(header(box[0]));r['resources_before_transport']=t.resources(process);r['cpu_ms_before_transport']=t.s.cpu_ms(process)
        (output/'report.json').write_text(json.dumps(r,indent=2)+'\n')
        if capture:raw=Path(capture).open('xb')
        digest=hashlib.sha256();received=[0]
        def pixels():
            try:
                while received[0]<r['bytes']:
                    chunk=process.stdout.read(min(1048576,r['bytes']-received[0]))
                    assert chunk,'pixel payload ended early'
                    digest.update(chunk);received[0]+=len(chunk)
                    if raw:raw.write(chunk)
            except Exception as error:errors.append(error)
        reader=threading.Thread(target=pixels,daemon=True);readers.append(reader);reader.start()
        process.stdin.write(b'GO\n');process.stdin.flush();reader.join(20)
        assert not reader.is_alive(),'pixel transport exceeded20s budget'
        assert not errors,repr(errors)
        assert process.wait(timeout=4)==0
        assert process.stdout.read(1)==b'','unexpected trailing pixel bytes'
        r.update(pixel_sha256=digest.hexdigest(),received_bytes=received[0],verdict='MEASUREMENT_PASS')
    except BaseException as error:
        primary_error=error
        r.update(verdict='MEASUREMENT_FAILED',error=repr(error));raise
    finally:
        cleanup_errors=[]
        def cleanup(label, action):
            try:
                return action()
            except BaseException as error:
                cleanup_errors.append(label+': '+repr(error))
                return None
        terminal=cleanup('poll',process.poll) is not None
        if not terminal:
            cleanup('kill owned child',process.kill)
            cleanup('wait owned child',lambda:process.wait(timeout=4))
            terminal=cleanup('final poll',process.poll) is not None
        for reader in readers:
            cleanup('join reader',lambda reader=reader:reader.join(2))
        readers_terminal=all(not reader.is_alive() for reader in readers)
        if not readers_terminal:cleanup_errors.append('reader still alive after bounded join')
        r['exit_code']=process.returncode
        r['stderr']=''
        if terminal:
            data=cleanup('read terminal stderr',process.stderr.read)
            if data is not None:r['stderr']=data.decode('utf-8',errors='replace')
        else:cleanup_errors.append('owned child is not terminal')
        cleanup('close stdin',process.stdin.close)
        cleanup('close stderr',process.stderr.close)
        if readers_terminal:
            cleanup('close stdout',process.stdout.close)
            if raw:cleanup('close payload capture',raw.close)
        r['reader_cleanup_terminal']=readers_terminal
        r['child_cleanup_terminal']=terminal
        r['cleanup_errors']=cleanup_errors
        if cleanup_errors:r['verdict']='MEASUREMENT_FAILED'
        cleanup('write worker report',lambda:(output/'report.json').write_text(json.dumps(r,indent=2)+'\n'))
        if cleanup_errors:
            if primary_error is not None:
                primary_error.add_note('worker cleanup: '+repr(cleanup_errors))
            else:
                raise RuntimeError('worker cleanup: '+repr(cleanup_errors))
    return r
