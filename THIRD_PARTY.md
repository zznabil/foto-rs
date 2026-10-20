# Third-party notices

Foto is GPL-3.0-or-later. Its Windows API bindings use their upstream MIT licenses. The Rust standard library and its bundled components retain their upstream licenses.

Release packages include the resolved Cargo dependency inventory, package license texts, and the Rust toolchain's complete library copyright notices. Build-time proc-macro packages are identified as dependencies rather than claimed to be runtime DLLs. Windows system DLLs are supplied by Windows and are not redistributed in the package.

Pillow generates synthetic test inputs only. Python, Pillow, CI tools and the Rust compiler are development tools and are not shipped in foto.exe. Their installation terms remain with their upstream projects.

The SPDX 2.3 SBOM inventories the Cargo dependency closure, with the Rust toolchain identified as a build tool. It does not inventory Windows system DLL internals or every Rust standard-library subcomponent; the separate Rust copyright file supplies those notices. An inventory is not a vulnerability assessment or certification.
