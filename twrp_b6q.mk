# Inherit from those products. Most specific first.
$(call inherit-product, $(SRC_TARGET_DIR)/product/core_64_bit_only.mk)
$(call inherit-product, $(SRC_TARGET_DIR)/product/full_base_telephony.mk)

# Inherit some common TWRP stuff.
$(call inherit-product, vendor/twrp/config/common.mk)

# Inherit from b6q device
$(call inherit-product, device/samsung/b6q/device.mk)

PRODUCT_DEVICE := b6q
PRODUCT_NAME := twrp_b6q
PRODUCT_BRAND := samsung
PRODUCT_MODEL := SM-F741B
PRODUCT_MANUFACTURER := samsung
PRODUCT_GMS_CLIENTID_BASE := android-samsung-ss

PRODUCT_BUILD_PROP_OVERRIDES += \
    PRIVATE_BUILD_DESC="b6qxxx-user 14 UP1A.231005.007 F741BXXS2CYL5 release-keys"

BUILD_FINGERPRINT := samsung/b6qxxx/b6q:14/UP1A.231005.007/F741BXXS2CYL5:user/release-keys
