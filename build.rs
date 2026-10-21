// SPDX-License-Identifier: GPL-3.0-or-later
use std::{env, fs, path::PathBuf, process::Command};

fn main() {
    println!("cargo:rerun-if-changed=Cargo.toml");
    println!("cargo:rerun-if-changed=build.rs");
    if env::var("CARGO_CFG_TARGET_OS").as_deref() != Ok("windows") {
        return;
    }
    let version = env::var("CARGO_PKG_VERSION").unwrap();
    let numbers = version.split('.').collect::<Vec<_>>();
    assert_eq!(numbers.len(), 3);
    let numeric = format!("{},{},{},0", numbers[0], numbers[1], numbers[2]);
    let output = PathBuf::from(env::var_os("OUT_DIR").unwrap());
    let script = output.join("foto.rc");
    let resource = output.join("foto.res");
    fs::write(
        &script,
        format!(
            r#"#pragma code_page(65001)
1 VERSIONINFO
FILEVERSION {numeric}
PRODUCTVERSION {numeric}
FILEFLAGSMASK 0x3fL
FILEFLAGS 0
FILEOS 0x40004L
FILETYPE 0x1L
FILESUBTYPE 0
BEGIN
  BLOCK "StringFileInfo"
  BEGIN
    BLOCK "040904b0"
    BEGIN
      VALUE "CompanyName", "Foto contributors\0"
      VALUE "FileDescription", "Foto native photo viewer\0"
      VALUE "FileVersion", "{version}\0"
      VALUE "InternalName", "foto\0"
      VALUE "LegalCopyright", "Copyright (C) 2026 Foto contributors; GPL-3.0-or-later\0"
      VALUE "OriginalFilename", "foto.exe\0"
      VALUE "ProductName", "Foto\0"
      VALUE "ProductVersion", "{version}\0"
    END
  END
  BLOCK "VarFileInfo"
  BEGIN
    VALUE "Translation", 0x0409, 1200
  END
END
"#
        ),
    )
    .unwrap();
    // Cargo can locate MSVC without a developer shell. Locate the installed SDK
    // resource compiler as well; the numeric resource needs no SDK headers.
    let mut compilers = Vec::new();
    if let Some(program_files) = env::var_os("ProgramFiles(x86)") {
        let directory = PathBuf::from(program_files).join("Windows Kits/10/bin");
        if let Ok(entries) = fs::read_dir(directory) {
            compilers = entries
                .filter_map(Result::ok)
                .map(|entry| entry.path().join("x64/rc.exe"))
                .filter(|path| path.is_file())
                .collect();
            compilers.sort();
            compilers.reverse();
        }
    }
    compilers.push(PathBuf::from("rc.exe"));
    for compiler in compilers {
        if let Ok(result) = Command::new(compiler)
            .args(["/nologo", "/fo"])
            .arg(&resource)
            .arg(&script)
            .output()
        {
            if result.status.success() {
                println!("cargo:rustc-link-arg-bin=foto={}", resource.display());
                return;
            }
            panic!(
                "Windows resource compilation failed: {}{}",
                String::from_utf8_lossy(&result.stdout),
                String::from_utf8_lossy(&result.stderr)
            );
        }
    }
    panic!("Install the Windows SDK resource compiler (rc.exe) with the MSVC build tools");
}
