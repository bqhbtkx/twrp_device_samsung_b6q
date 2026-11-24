$(call inherit-product, $(SRC_TARGET_DIR)/product/aosp_base.mk)
$(call inherit-product, $(SRC_TARGET_DIR)/product/core_64_bit.mk)

# Inherit from twrp common
$(call inherit-product, vendor/twrp/config/common.mk)

# Inherit from device
$(call inherit-product, device/samsung/b6q/device.mk)

PRODUCT_DEVICE := b6q
PRODUCT_NAME := twrp_b6q
PRODUCT_BRAND := samsung
PRODUCT_MODEL := SM-F741B
PRODUCT_MANUFACTURER := samsung
