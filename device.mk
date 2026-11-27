#
# Copyright (C) 2026 The TeamWin Recovery Project
#
# SPDX-License-Identifier: Apache-2.0
#

DEVICE_PATH := device/samsung/b6q

# Shipping API level (capped to 32 for twrp-12.1 SDK compatibility; device shipped with 34)
PRODUCT_SHIPPING_API_LEVEL := 32

# Dynamic partitions
PRODUCT_USE_DYNAMIC_PARTITIONS := true

# Recovery properties (from stock SM-F741BXXS2CYL5 prop.default / VENDOR/build.prop)
PRODUCT_DEFAULT_PROPERTY_OVERRIDES += \
    ro.recovery.usb.vid=18D1 \
    ro.recovery.usb.adb.pid=D001 \
    ro.recovery.usb.fastboot.pid=4EE0 \
    ro.boot.dynamic_partitions=true \
    ro.build.ab_update=false \
    ro.minui.pixel_format=RGBX_8888 \
    ro.sf.lcd_density=480 \
    ro.surface_flinger.sub_lcd_density=340 \
    ro.product.board=pineapple \
    ro.board.platform=pineapple \
    ro.soc.manufacturer=QTI \
    vendor.usb.controller=a600000.dwc3

# Enable fastbootd
PRODUCT_PACKAGES += \
    android.hardware.fastboot@1.0-impl-mock \
    fastbootd

# Recovery fstab & TWRP flags
PRODUCT_COPY_FILES += \
    $(DEVICE_PATH)/recovery/root/system/etc/recovery.fstab:$(TARGET_COPY_OUT_RECOVERY)/root/system/etc/recovery.fstab \
    $(DEVICE_PATH)/recovery/root/system/etc/twrp.flags:$(TARGET_COPY_OUT_RECOVERY)/root/system/etc/twrp.flags

# Init scripts
PRODUCT_COPY_FILES += \
    $(DEVICE_PATH)/recovery/root/init.recovery.qcom.rc:$(TARGET_COPY_OUT_RECOVERY)/root/init.recovery.qcom.rc \
    $(DEVICE_PATH)/recovery/root/init.recovery.samsung.rc:$(TARGET_COPY_OUT_RECOVERY)/root/init.recovery.samsung.rc \
    $(DEVICE_PATH)/recovery/root/init.recovery.usb.rc:$(TARGET_COPY_OUT_RECOVERY)/root/init.recovery.usb.rc

# Prebuilt stock recovery kernel modules (including synaptics_spi_fold, synaptics_i2c_fold, msm_drm, ufs_qcom, dwc3-msm)
RECOVERY_MODULES_PATH := $(DEVICE_PATH)/prebuilt/modules
PRODUCT_COPY_FILES += $(foreach file,$(wildcard $(RECOVERY_MODULES_PATH)/*),\
    $(file):$(TARGET_COPY_OUT_RECOVERY)/root/lib/modules/$(notdir $(file)))

# Ensure modules.load also exists alongside modules.load.recovery
PRODUCT_COPY_FILES += \
    $(RECOVERY_MODULES_PATH)/modules.load.recovery:$(TARGET_COPY_OUT_RECOVERY)/root/lib/modules/modules.load
