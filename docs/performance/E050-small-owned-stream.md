# E050: reject the bounded small-file memory-stream decoder

The optional owned-memory-stream path made tiny JPEG/PNG loads faster in this component screen, but failed the fixed memory and fallback-time regression guards. The candidate was rejected and production files restored. This PR adds only the experiment report; it proposes no decoder change.

The local streak advanced once, from 27 to 28 valid consecutive plateaus. In this protocol a demonstrated regression rejects a distinct candidate and counts once. A plateau does not mean that the candidate was safe to ship. There are now 38 performance-evaluated candidates, ten unresolved candidates and zero retained improvements in this streak. The 100-plateau goal remains incomplete.

## Hypothesis and intervention

For regular JPEG/JPG/JFIF/PNG inputs no larger than 65,536 bytes, open a file, inspect its metadata, read at most the observed length plus one into a fallibly allocated initialized buffer, copy it into `SHCreateMemStream`, and create a Microsoft JPEG/PNG WIC decoder from that owned stream. All size, read, allocation, container or vendor failures use the original filename decoder. The rest of EXIF handling, scaling, premultiplied output, first-frame selection and exact-capacity pixel reuse stays unchanged.

The extra byte detects growth beyond the observed length. The buffer and stream wrapper leave scope before WIC frame reads, so borrowed caller storage is never used by the proposed product path. No dependency, UI feature, cache-limit or machine-setting change was included.

## Scope and provenance

- Local base revision `16bde7b054695c4b643f22e4598b39341a1f07a2` plus ongoing study changes. The source fingerprints below identify the actual tested decoder; the base commit alone does not.
- The integration base contains unresolved E010/E015 work. This rejection accepts neither that work nor the upstream release.
- Rust 1.96.0, Python 3.14.8, one Windows 11 x64 host. Release optimization level 3, full LTO, one codegen unit and static CRT in both arms.
- Four warm synthetic inputs, all decoding to 64 x 48 PBGRA: an 831-byte JPEG, a 169-byte PNG, that PNG padded to exactly 65,536 bytes, and that PNG padded to 65,537 bytes (filename fallback). Padding permits a size-boundary comparison without changing decoded content; it does not represent every real-world large input.

## Correctness before timing

- 23 Rust tests, strict all-target Clippy and formatting passed. New tests cover 0/65,535/65,536/65,537-byte boundaries, growth, EOF/shrink, injected read failure, missing/invalid files, case-insensitive extensions and renamed BMP/TIFF/unsupported suffix fallbacks.
- 40 fixtures passed complete PBGRA, dimensions and oriented-original-size parity against the original filename decoder. This included all 31 prior format/EXIF fixtures and nine boundary/renamed fixtures. Fresh output and poisoned exact-capacity reuse were checked, including pointer reuse; four actual decodes per fixture, 160 total. Deliberate one-byte mutations were rejected.
- An independent ownership capability check overwrote/dropped caller bytes and churned the same allocation class before full pixel reads. The owned stream passed for JPEG, PNG and alpha PNG. The known borrowed-storage variant failed after zeroing its still-live input, calibrating the lifetime oracle without dereferencing freed storage.
- Current candidate native journeys J06/J07/J13/J16/J21/J22/J23/J24 and the portable-import audit passed.

## Frozen measurement and controls

Each child performed 4,096 complete fresh-buffer loads. The endpoint includes file open/metadata/read, stream allocation and copy, vendor check, WIC metadata/EXIF/conversion and pixel allocation/copy. It is not an initialization-only timer. COM factory creation is outside the per-load timer and inside whole-process CPU measurements. Pixel transport occurs after resource counters are read.

Per case: four unchanged-control AA pairs and 12 alternating AB/BA pairs, with rotating case order. Analysis uses six two-pair blocks, 19,999 bootstrap draws and approximate 99% family intervals over 16 formal fields: per-load latency plus mean whole-process CPU, peak commit and final private memory for each case. Latency uses BCa and resources use percentile intervals. Loads within a process are correlated. Noise guards stay `max(10%, 2 * median absolute AA percentage change)` with values over 25% treated as weak; both memory guards stay 10%. All 28 additional median resource checks are retained. No sample extension or guard relaxation occurred.

The valid cohort completed 128 comparison children plus 20 control children, 296 valid raw CPU records and 622,592 actual timed complete decodes. Every case passed actual 1,000 ms single-delay detection (at least 750 ms observed total difference), doubled-load wall/CPU controls, retained 32 MiB private/peak-memory controls, full payload hashes and one-byte payload negatives. Process-time and cycle counters were read twice and checked before use.

The first calibration cohort is preserved as failed: its known 200 ms delay produced only a 133.165 ms difference, below the required 150 ms. Five children and ten CPU reads completed; zero AA or candidate AB observations were collected. A faster subsequent pipeline partly masked that small delay; the exact cause was not isolated. The new independent cohort changed only the known positive delay from 200 to 1,000 ms and kept the 75% detection requirement. The failed cohort was never pooled, counted or rewritten as passing.

To avoid blocking the supervisor on a full stderr pipe, probes publish 32 sums of 128 load timings (64 sums for the doubled-work control). Any reported block-mean tails are descriptive and are not individual-decode p95/p99 estimates. Both arm probes used the same bounded output protocol before any timing data.

## Results and decision

Negative percentages mean lower cost. The intervals describe this component screen, not application UI latency.

| Case / metric | Change | Approximate interval | Guard |
| --- | ---: | ---: | ---: |
| jpeg.decode_ms | -18.5817% | [-20.7363%, -17.1533%] | 10.0000% |
| jpeg.CPU_mean_ms | -18.3908% | [-21.2815%, -15.6682%] | 10.5263% |
| jpeg.peak_commit_mean_bytes | +8.4043% | [+7.7812%, +8.8746%] | 10.0000% |
| jpeg.private_mean_bytes | +8.4043% | [+7.7812%, +8.8746%] | 10.0000% |
| png.decode_ms | -16.0920% | [-17.3230%, -15.3244%] | 10.0000% |
| png.CPU_mean_ms | -13.9205% | [-17.6471%, -11.7978%] | 10.0000% |
| png.peak_commit_mean_bytes | +7.4307% | [+6.4562%, +8.2073%] | 10.0000% |
| png.private_mean_bytes | +7.4127% | [+6.4562%, +8.1713%] | 10.0000% |
| exact64k.decode_ms | -2.0935% | [-3.2168%, -1.5182%] | 10.0000% |
| exact64k.CPU_mean_ms | -1.4286% | [-4.5326%, +1.1628%] | 10.0000% |
| exact64k.peak_commit_mean_bytes | +16.5858% | [+15.3836%, +18.5046%] | 10.0000% |
| exact64k.private_mean_bytes | +15.4897% | [+14.3517%, +16.9203%] | 10.0000% |
| fallback.decode_ms | +49.6787% | [+47.0285%, +58.6390%] | 10.0000% |
| fallback.CPU_mean_ms | +49.2958% | [+43.0939%, +55.5556%] | 10.0000% |
| fallback.peak_commit_mean_bytes | +1.5459% | [+1.1099%, +2.0246%] | 10.0000% |
| fallback.private_mean_bytes | +1.5459% | [+1.1099%, +2.0246%] | 10.0000% |

The tiny JPEG and PNG timing gains were not independently confirmed or retained. At exactly 64 KiB, peak commit increased 16.5858% (interval +15.3836% to +18.5046%) and final private memory increased 15.4897% (+14.3517% to +16.9203%), both beyond the fixed 10% guards. The 65,537-byte fallback took 49.6787% longer (+47.0285% to +58.6390%) and used 49.2958% more CPU (+43.0939% to +55.5556%). All AA guards were nonweak. Two of 28 additional resource points also failed: exact-boundary private memory and peak commit.

The fallback slowdown is consistent with opening and inspecting the file before opening it again through the original decoder. That explanation is an inference; this study did not separately isolate each syscall or allocator contribution.

Decision: `REJECTED_DEMONSTRATED_COMPONENT_PERFORMANCE_OR_RESOURCE_REGRESSION`. Demonstrated harm takes priority over the apparent small-input gain. Source, Cargo files, default executable and distribution executable match their pre-experiment fingerprints. No optimization was retained and the streak was not reset.

## Evidence fingerprints

These refer to locally retained evidence; generated binaries, raw local paths, credentials and photos are not included. This report alone is not a standalone reproducible benchmark package.

- control decoder: `99ee3495915d35f9698ef920548ebff57ca4e30e7399fa0b8ecc29d680355557`
- candidate decoder: `bb0d530e5ec2d86892bfef7dea36c77ac66400269271bb287ba78f437bd13813`
- ownership capability: `10d85908aa441d28eb58af1a11a70b4fe31ec88830fd188ca95c75cc34b15778`
- correctness manifest: `6678dd2b88d9018f0b723158ae7b3bc56217b9e31d6d7cd87b7f18306c9c3d53`
- failed first calibration: `07b3815c056cfbcea5349f09ba2fe2376bb6f024e468ac12a7bb1b5907cf682b`
- valid cohort protocol: `d0c25352ee429b659cf118d34e298ac108012acfb5b5f744de76e7d3746aa91e`
- valid cohort observations: `7ae42a7f050511de54661eb223d413dda863d739c26eaf856847c980ba6ab25c`
- analysis: `7bdc958c8372e663283d6e5016052f1f386b1df28c7439244e68216e1f6eaf32`
- decision: `d747a298445d04fa7f4a8dccc86b01dc61e90c876b76cfb2d8936025540f3057`

## Limits and revisit condition

Full 31-journey/600-second acceptance, independent gain confirmation and original-base/current-upstream integration acceptance were skipped after the valid rejection. The study makes no human-UAT, cold-cache, Windows 10, physical-input, native UI tail-latency or universal no-regression claim. Current upstream pins a newer toolchain; these historical local checks do not replace its clean-commit release-verification gate. Remote CI status for this documentation PR must be read separately.

Revisit only with a materially different bounded design that addresses both the fallback overhead and boundary memory cost, and a new frozen protocol. Repeating the same candidate or publishing this report does not add another plateau.
