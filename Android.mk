LOCAL_PATH := $(call my-dir)

ifeq ($(TARGET_DEVICE),b6q)
include $(call all-makefiles-under,$(LOCAL_PATH))
endif
