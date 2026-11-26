# TWRP Device Tree for Samsung Galaxy Z Flip6 (SM-F741B / b6q)

Generated from scratch from stock firmware `AP_F741BXXS2CYL5_F741BXXS2CYL5_MQB105184587_REV00_user_low_ship_MULTI_CERT_meta_OS16.tar` (Android 16 / One UI 8, Vendor Android 14).

## Extracted Device Parameters
- **Device / Codename**: `SM-F741B` / `b6q` (`b6qxxx`)
- **SoC / Platform**: Qualcomm Snapdragon 8 Gen 3 (`pineapple` / `sm8650`, `arm64-v8a` 64-bit only)
- **Partition Scheme**: Non-A/B (`allow_non_ab=true`), Dynamic Partitions (`super`: 13,718,519,808 bytes)
- **Kernel**: `6.1.128-android14-11-31998796-abF741BXXS2CYL5`
- **Recovery Boot Header**: Header v2, `pagesize=4096`, `recovery_size=110034944`, LZ4 legacy ramdisk, includes `dtb` and `recovery_dtbo`
- **Touchscreen Modules**: `synaptics_spi_fold.ko`, `synaptics_i2c_fold.ko` (plus all 402 recovery modules from stock `recovery.img`)

## Building from Source (`twrp-14.1`)
Minimum recommended RAM + Swap: **24–32 GB** (e.g. 9.4 GiB RAM + 24 GB swapfile) and ~80 GB free disk space.

```bash
export ALLOW_MISSING_DEPENDENCIES=true
. build/envsetup.sh
lunch twrp_b6q-eng
mka recoveryimage
```
