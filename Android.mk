LOCAL_PATH := $(call my-dir)

ifeq ($(TARGET_DEVICE),b6q)
include $(call all-subdir-makefiles,$(LOCAL_PATH))
endif
