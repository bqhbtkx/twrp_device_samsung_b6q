#
# Copyright (C) 2026 The TeamWin Recovery Project
#
# SPDX-License-Identifier: Apache-2.0
#

DEVICE_PATH := device/samsung/b6q

# Shipping API level
PRODUCT_SHIPPING_API_LEVEL := 34

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
    ro.crypto.metadata_init_delete_all_keys.enabled=true \
    vendor.gatekeeper.is_security_level_spu=0 \
    ro.hardware.keystore=mdfpp \
    ro.hardware.gatekeeper=mdfpp \
    ro.hardware.keystore_desede=true \
    ro.product.board=pineapple \
    ro.board.platform=pineapple \
    ro.soc.manufacturer=QTI \
    vendor.usb.controller=a600000.dwc3

# Enable fastbootd
PRODUCT_PACKAGES += \
    fastbootd

# Recovery fstab & TWRP flags
PRODUCT_COPY_FILES += \
    $(DEVICE_PATH)/recovery/root/system/etc/recovery.fstab:$(TARGET_COPY_OUT_RECOVERY)/root/system/etc/recovery.fstab \
    $(DEVICE_PATH)/recovery/root/system/etc/twrp.flags:$(TARGET_COPY_OUT_RECOVERY)/root/system/etc/twrp.flags

# Init scripts
PRODUCT_COPY_FILES += \
    $(DEVICE_PATH)/recovery/root/init.recovery.qcom.rc:$(TARGET_COPY_OUT_RECOVERY)/root/init.recovery.qcom.rc \
    $(DEVICE_PATH)/recovery/root/init.recovery.samsung.rc:$(TARGET_COPY_OUT_RECOVERY)/root/init.recovery.samsung.rc \
    $(DEVICE_PATH)/recovery/root/init.recovery.b6q.rc:$(TARGET_COPY_OUT_RECOVERY)/root/init.recovery.b6q.rc

# Prebuilt stock recovery kernel modules (including synaptics_spi_fold, synaptics_i2c_fold, msm_drm, ufs_qcom, dwc3-msm)
RECOVERY_MODULES_PATH := $(DEVICE_PATH)/prebuilt/modules
PRODUCT_COPY_FILES += $(foreach file,$(wildcard $(RECOVERY_MODULES_PATH)/*),\
    $(file):$(TARGET_COPY_OUT_RECOVERY)/root/lib/modules/$(notdir $(file)))

# Ensure modules.load also exists alongside modules.load.recovery
PRODUCT_COPY_FILES += \
    $(RECOVERY_MODULES_PATH)/modules.load.recovery:$(TARGET_COPY_OUT_RECOVERY)/root/lib/modules/modules.load
