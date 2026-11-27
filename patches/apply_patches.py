#!/usr/bin/env python3
"""Apply b6q-specific patches to TeamWin android_bootable_recovery (twrp-12.1):
1. minuitwrp/events.cpp:
   - Unconditionally ignore conflicting sensors/touchpad/haptic inputs
   - Route sec_touchscreen (open) vs sec_touchscreen2 (folded) via hall_ic/flip_status & SW_LID
   - Implement Linux input-ff vibration via sec_vibrator_inputff (aw8624x_haptic)
2. minuitwrp/graphics_drm.cpp:
   - Support dynamic switching between DSI-1 (1080x2640) and DSI-2 (720x748) on fold/unfold
   - Scale 1080x2640 framebuffer to 720x748 when folded, keep only 1 screen & backlight active
3. twrp-functions.cpp:
   - Route Set_Brightness to panel0-backlight (open) or panel1-backlight (folded), zeroing the other
4. gui/gui.cpp:
   - Trigger immediate re-render & flip when fold state changes
"""
import pathlib
import sys


def patch_events(path: pathlib.Path) -> None:
    src = path.read_text(encoding="utf-8")
    if "b6q_is_folded" in src:
        print(f"{path} already patched.")
        return

    # 1. Include <pthread.h> and <time.h> and add fold + vibrator helpers
    inc_target = "#include <fstream>\n"
    if inc_target not in src:
        raise SystemExit(f"ERROR: include anchor not found in {path}")

    helpers = """#include <fstream>
#include <pthread.h>
#include <time.h>

static pthread_mutex_t b6q_vib_lock = PTHREAD_MUTEX_INITIALIZER;
static int b6q_vib_fd = -1;
static int b6q_vib_effect_id = -1;
static volatile int b6q_folded_cached = 0;
static struct timespec b6q_last_fold_poll = {0, 0};

static bool b6q_read_fold_sysfs(void) {
    int fd = open("/sys/class/sec/hall_ic/flip_status", O_RDONLY);
    if (fd < 0) return false;
    char buf[8] = {0};
    ssize_t n = read(fd, buf, sizeof(buf) - 1);
    close(fd);
    if (n > 0 && buf[0] == '0') return true;
    return false;
}

static void b6q_set_folded(bool folded) {
    b6q_folded_cached = folded ? 1 : 0;
    clock_gettime(CLOCK_MONOTONIC, &b6q_last_fold_poll);
}

static bool b6q_is_folded(void) {
    struct timespec now;
    clock_gettime(CLOCK_MONOTONIC, &now);
    long elapsed_ms = (now.tv_sec - b6q_last_fold_poll.tv_sec) * 1000L +
                      (now.tv_nsec - b6q_last_fold_poll.tv_nsec) / 1000000L;
    if (b6q_last_fold_poll.tv_sec == 0 || elapsed_ms >= 100 || elapsed_ms < 0) {
        b6q_folded_cached = b6q_read_fold_sysfs() ? 1 : 0;
        b6q_last_fold_poll = now;
    }
    return b6q_folded_cached != 0;
}
"""
    src = src.replace(inc_target, helpers, 1)

    # 2. Replace vibrate() body to support sec_vibrator_inputff (FF_CONSTANT) first
    vib_anchor = """int vibrate(int timeout_ms)
{
    if (timeout_ms > 10000) timeout_ms = 1000;"""
    if vib_anchor not in src:
        raise SystemExit(f"ERROR: vibrate anchor not found in {path}")

    vib_replacement = """int vibrate(int timeout_ms)
{
    if (timeout_ms <= 0) return 0;
    if (timeout_ms > 10000) timeout_ms = 1000;

    pthread_mutex_lock(&b6q_vib_lock);
    if (b6q_vib_fd >= 0) {
        struct input_event gain_ev;
        memset(&gain_ev, 0, sizeof(gain_ev));
        gain_ev.type = EV_FF;
        gain_ev.code = FF_GAIN;
        gain_ev.value = 0xFFFF;
        ssize_t gain_ret = write(b6q_vib_fd, &gain_ev, sizeof(gain_ev));
        (void)gain_ret;

        struct ff_effect effect;
        memset(&effect, 0, sizeof(effect));
        effect.type = FF_CONSTANT;
        effect.id = (int16_t)b6q_vib_effect_id;
        effect.replay.length = (uint16_t)timeout_ms;
        effect.replay.delay = 0;
        effect.u.constant.level = 0x7FFF;
        if (ioctl(b6q_vib_fd, EVIOCSFF, &effect) < 0 && b6q_vib_effect_id != -1) {
            b6q_vib_effect_id = -1;
            effect.id = -1;
            if (ioctl(b6q_vib_fd, EVIOCSFF, &effect) == 0) {
                b6q_vib_effect_id = effect.id;
            }
        } else {
            b6q_vib_effect_id = effect.id;
        }
        if (b6q_vib_effect_id >= 0) {
            struct input_event play;
            memset(&play, 0, sizeof(play));
            play.type = EV_FF;
            play.code = (uint16_t)b6q_vib_effect_id;
            play.value = 1;
            ssize_t play_ret = write(b6q_vib_fd, &play, sizeof(play));
            (void)play_ret;
            pthread_mutex_unlock(&b6q_vib_lock);
            return 0;
        }
    }
    pthread_mutex_unlock(&b6q_vib_lock);"""
    src = src.replace(vib_anchor, vib_replacement, 1)

    # 3. Replace the entire #ifdef WHITELIST_INPUT ... #endif block in vk_init() unconditionally
    #    (since BoardConfigSoong.mk always defines TW_INPUT_BLACKLIST=" ")
    bl_start = "#ifdef WHITELIST_INPUT"
    bl_end = "    strcat(vk_path, e->deviceName);"
    s_idx = src.find(bl_start)
    e_idx = src.find(bl_end, s_idx)
    if s_idx < 0 or e_idx < 0:
        raise SystemExit(f"ERROR: WHITELIST_INPUT block not found in {path}")

    ignored_names = [
        "bma250",
        "bma150",
        "hbtp_vm",
        "als_rear",
        "akm-digital-hall",
        "certify_hall",
        "meta_event",
        "sec_touchpad",
        "sec_touchproximity",
        "sec_touchproximity2",
        "sec_vibrator_inputff",
    ]
    cond = " ||\n        ".join(f'strcmp(e->deviceName, "{n}") == 0' for n in ignored_names)
    new_block = f"""    if ({cond})
    {{
        LOGI("Blacklisting input device: %s\\n", e->deviceName);
        e->ignored = 1;
    }}

"""
    src = src[:s_idx] + new_block + src[e_idx:]

    # 4. In ev_init(), open sec_vibrator_inputff O_RDWR for FF ioctls
    ev_init_anchor = """            /* Load virtualkeys if there are any */
            vk_init(&evs[ev_count]);"""
    if ev_init_anchor not in src:
        raise SystemExit(f"ERROR: ev_init anchor not found in {path}")
    ev_init_repl = """            /* Load virtualkeys if there are any */
            vk_init(&evs[ev_count]);

            if (strcmp(evs[ev_count].deviceName, "sec_vibrator_inputff") == 0) {
                pthread_mutex_lock(&b6q_vib_lock);
                if (b6q_vib_fd < 0) {
                    b6q_vib_fd = openat(dirfd(dir), de->d_name, O_RDWR);
                    b6q_vib_effect_id = -1;
                }
                pthread_mutex_unlock(&b6q_vib_lock);
            }"""
    src = src.replace(ev_init_anchor, ev_init_repl, 1)

    # 5. In ev_exit(), close b6q_vib_fd
    ev_exit_anchor = """void ev_exit(void)
{"""
    if ev_exit_anchor not in src:
        raise SystemExit(f"ERROR: ev_exit anchor not found in {path}")
    ev_exit_repl = """void ev_exit(void)
{
    pthread_mutex_lock(&b6q_vib_lock);
    if (b6q_vib_fd >= 0) {
        close(b6q_vib_fd);
        b6q_vib_fd = -1;
        b6q_vib_effect_id = -1;
    }
    pthread_mutex_unlock(&b6q_vib_lock);"""
    src = src.replace(ev_exit_anchor, ev_exit_repl, 1)

    # 6. In vk_modify(), handle "flip" SW_LID and route only active screen touch
    vk_mod_anchor = """    // This is used to ditch useless event handlers, like an accelerometer
    if (e->ignored)     return 1;"""
    if vk_mod_anchor not in src:
        raise SystemExit(f"ERROR: vk_modify anchor not found in {path}")

    vk_mod_repl = """    // This is used to ditch useless event handlers, like an accelerometer
    if (e->ignored)     return 1;

    static int b6q_last_touch_folded = -1;
    if (strcmp(e->deviceName, "flip") == 0) {
        if (ev->type == EV_SW && ev->code == SW_LID) {
            b6q_set_folded(ev->value != 0);
            downX = -1;
            downY = -1;
            discard = 0;
            lastWasSynReport = 0;
            touchReleaseOnNextSynReport = 0;
            ev->type = EV_KEY;
            ev->code = KEY_RESERVED;
            ev->value = 0;
            return 0;
        }
        return 1;
    }

    int cur_folded = b6q_is_folded() ? 1 : 0;
    if (b6q_last_touch_folded != cur_folded) {
        b6q_last_touch_folded = cur_folded;
        downX = -1;
        downY = -1;
        discard = 0;
        lastWasSynReport = 0;
        touchReleaseOnNextSynReport = 0;
    }
    if (strcmp(e->deviceName, "sec_touchscreen") == 0 && cur_folded)
        return 1;
    if (strcmp(e->deviceName, "sec_touchscreen2") == 0 && !cur_folded)
        return 1;"""
    src = src.replace(vk_mod_anchor, vk_mod_repl, 1)

    path.write_text(src, encoding="utf-8")
    print(f"Patched {path}")


def patch_graphics_drm(path: pathlib.Path) -> None:
    src = path.read_text(encoding="utf-8")
    if "b6q_drm_folded" in src:
        print(f"{path} already patched.")
        return

    # Replace everything from "static drm_surface *drm_surfaces[2];" through end of file
    anchor = "static drm_surface *drm_surfaces[2];"
    idx = src.find(anchor)
    if idx < 0:
        raise SystemExit(f"ERROR: drm_surfaces anchor not found in {path}")

    # Also ensure <vector> is included if needed - we can use fixed arrays / no extra STL needed
    replacement = r"""static drm_surface *drm_surfaces[2];
static int current_buffer;
static GRSurface *draw_buf = nullptr;

static drmModeCrtc *main_monitor_crtc;
static drmModeConnector *main_monitor_connector;

static int drm_fd = -1;

static bool current_blank_state = true;
static int fb_prop_id;
static struct Crtc crtc_res;
static struct Connector conn_res;
static struct Plane plane_res[NUM_PLANES];
static uint32_t number_of_lms = DEFAULT_NUM_LMS;

struct B6qDrmDisplay {
  drmModeConnector *connector;
  drmModeCrtc *crtc;
  int crtc_index;
  struct Crtc crtc_res;
  struct Connector conn_res;
  struct Plane plane_res[NUM_PLANES];
  uint32_t number_of_lms;
  uint32_t fb_prop_id;
  drm_surface *surfaces[2];
  int width;
  int height;
  bool valid;
};

static struct B6qDrmDisplay inner_disp;
static struct B6qDrmDisplay outer_disp;
static bool b6q_drm_folded = false;

static bool b6q_read_folded_state(void) {
  int fd = open("/sys/class/sec/hall_ic/flip_status", O_RDONLY);
  if (fd < 0) return false;
  char buf[8] = {0};
  ssize_t n = read(fd, buf, sizeof(buf) - 1);
  close(fd);
  return (n > 0 && buf[0] == '0');
}

static void b6q_write_sysfs(const char *path, const char *val) {
  int fd = open(path, O_WRONLY);
  if (fd >= 0) {
    ssize_t n = write(fd, val, strlen(val));
    (void)n;
    close(fd);
  }
}

static int b6q_read_saved_brightness(void) {
  int fd = open("/tmp/.b6q_brightness", O_RDONLY);
  if (fd >= 0) {
    char buf[32] = {0};
    ssize_t n = read(fd, buf, sizeof(buf) - 1);
    close(fd);
    if (n > 0) {
      int v = atoi(buf);
      if (v >= 0 && v <= 12750) return v;
    }
  }
  return 4000;
}

static void b6q_apply_backlights(bool folded) {
  int saved = b6q_read_saved_brightness();
  char buf[32];
  if (folded) {
    b6q_write_sysfs("/sys/class/backlight/panel0-backlight/brightness", "0");
    int sub_val = (saved <= 0) ? 0 : (saved * 7650) / 12750;
    if (saved > 0 && sub_val < 200) sub_val = 200;
    if (sub_val > 7650) sub_val = 7650;
    snprintf(buf, sizeof(buf), "%d", sub_val);
    b6q_write_sysfs("/sys/class/backlight/panel1-backlight/brightness", buf);
  } else {
    b6q_write_sysfs("/sys/class/backlight/panel1-backlight/brightness", "0");
    snprintf(buf, sizeof(buf), "%d", saved);
    b6q_write_sysfs("/sys/class/backlight/panel0-backlight/brightness", buf);
  }
}

static void b6q_activate_display_state(struct B6qDrmDisplay *d) {
  main_monitor_connector = d->connector;
  main_monitor_crtc = d->crtc;
  crtc_res = d->crtc_res;
  conn_res = d->conn_res;
  for (int i = 0; i < NUM_PLANES; ++i) {
    plane_res[i] = d->plane_res[i];
  }
  number_of_lms = d->number_of_lms;
  fb_prop_id = d->fb_prop_id;
  drm_surfaces[0] = d->surfaces[0];
  drm_surfaces[1] = d->surfaces[1];
}

#define find_prop_id(_res, type, Type, obj_id, prop_name, prop_id)    \
  do {                                                                \
    int j = 0;                                                        \
    int prop_count = 0;                                               \
    struct Type *obj = NULL;                                          \
    obj = (_res);                                                     \
    prop_count = (int)obj->props->count_props;                        \
    for (j = 0; j < prop_count; ++j)                                  \
      if (!strcmp(obj->props_info[j]->name, prop_name))               \
        break;                                                        \
    (prop_id) = (j == prop_count)? 0 : obj->props_info[j]->prop_id;   \
  } while (0)

#define add_prop(res, type, Type, id, id_name, id_val) \
  find_prop_id(res, type, Type, id, id_name, prop_id); \
  if (prop_id)                                         \
    drmModeAtomicAddProperty(atomic_req, id, prop_id, id_val);

enum sde_rm_topology_name {
  SDE_RM_TOPOLOGY_NONE = 0,
  SDE_RM_TOPOLOGY_SINGLEPIPE,
  SDE_RM_TOPOLOGY_SINGLEPIPE_DSC,
  SDE_RM_TOPOLOGY_SINGLEPIPE_VDC,
  SDE_RM_TOPOLOGY_DUALPIPE,
  SDE_RM_TOPOLOGY_DUALPIPE_DSC,
  SDE_RM_TOPOLOGY_DUALPIPE_3DMERGE,
  SDE_RM_TOPOLOGY_DUALPIPE_3DMERGE_DSC,
  SDE_RM_TOPOLOGY_DUALPIPE_DSCMERGE,
  SDE_RM_TOPOLOGY_PPSPLIT,
  SDE_RM_TOPOLOGY_QUADPIPE_3DMERGE,
  SDE_RM_TOPOLOGY_QUADPIPE_3DMERGE_DSC,
  SDE_RM_TOPOLOGY_QUADPIPE_DSCMERGE,
  SDE_RM_TOPOLOGY_QUADPIPE_DSC4HSMERGE,
};

static uint32_t get_lm_number(const std::string &topology) {
  if (topology == "sde_singlepipe") return 1;
  if (topology == "sde_singlepipe_dsc") return 1;
  if (topology == "sde_singlepipe_vdc") return 1;
  if (topology == "sde_dualpipe") return 2;
  if (topology == "sde_dualpipe_dsc") return 2;
  if (topology == "sde_dualpipe_3dmerge") return 2;
  if (topology == "sde_dualpipe_3dmerge_dsc") return 2;
  if (topology == "sde_dualpipe_dscmerge") return 2;
  if (topology == "sde_ppsplit") return 1;
  if (topology == "sde_quadpipe_3dmerge") return 4;
  if (topology == "sde_quadpipe_3dmerge_dsc") return 4;
  if (topology == "sde_quadpipe_dscmerge") return 4;
  if (topology == "sde_quadpipe_dsc4hsmerge") return 4;

  printf("invalid topology %s\n", topology.c_str());
  return DEFAULT_NUM_LMS;
}

static uint32_t get_topology_lm_number(int fd, uint32_t blob_id) {
  uint32_t num_lm = DEFAULT_NUM_LMS;
  drmModePropertyBlobRes *blob = drmModeGetPropertyBlob(fd, blob_id);
  if (!blob) return num_lm;

  const char *fmt_str = (const char *)(blob->data);
  std::stringstream stream(fmt_str);
  std::string line = {};
  const std::string topology = "topology=";

  while (std::getline(stream, line)) {
    if (line.find(topology) != std::string::npos) {
      num_lm = get_lm_number(std::string(line, topology.length()));
      break;
    }
  }

  drmModeFreePropertyBlob(blob);
  return num_lm;
}

static int find_plane_prop_id(uint32_t obj_id, const char *prop_name,
                              Plane *plane_res_arr) {
  int i, j = 0;
  int prop_count = 0;
  struct Plane *obj = NULL;

  for (i = 0; i < NUM_PLANES; ++i) {
    obj = &plane_res_arr[i];
    if (!obj || !obj->plane || obj->plane->plane_id != obj_id)
      continue;
    prop_count = (int)obj->props->count_props;
    for (j = 0; j < prop_count; ++j)
      if (!strcmp(obj->props_info[j]->name, prop_name))
        return obj->props_info[j]->prop_id;
    break;
  }

  return 0;
}

static int atomic_add_prop_to_plane(Plane *plane_res_arr, drmModeAtomicReq *req,
                                    uint32_t obj_id, const char *prop_name,
                                    uint64_t value) {
  uint32_t prop_id = find_plane_prop_id(obj_id, prop_name, plane_res_arr);
  if (prop_id == 0) {
    printf("Could not find obj_id = %d\n", obj_id);
    return -EINVAL;
  }
  if (drmModeAtomicAddProperty(req, obj_id, prop_id, value) < 0) {
    printf("Could not add prop_id = %d for obj_id %d\n", prop_id, obj_id);
    return -EINVAL;
  }
  return 0;
}

static int atomic_populate_plane(int plane, drmModeAtomicReqPtr atomic_req) {
  uint32_t src_x, src_y, src_w, src_h;
  uint32_t crtc_x, crtc_y, crtc_w, crtc_h;
  int width = main_monitor_crtc->mode.hdisplay;
  int height = main_monitor_crtc->mode.vdisplay;
  int zpos = 0;
  src_y = 0;
  src_w = width / number_of_lms;
  src_h = height;
  crtc_y = 0;
  crtc_w = width / number_of_lms;
  crtc_h = height;

  src_x = (width / number_of_lms) * plane;
  crtc_x = (width / number_of_lms) * plane;

  if (number_of_lms == 4)
    zpos = plane >> 1;

  atomic_add_prop_to_plane(plane_res, atomic_req,
                           plane_res[plane].plane->plane_id, "zpos", zpos);

  if (atomic_add_prop_to_plane(plane_res, atomic_req,
                               plane_res[plane].plane->plane_id, "FB_ID",
                               drm_surfaces[current_buffer]->fb_id))
    return -EINVAL;
  if (atomic_add_prop_to_plane(plane_res, atomic_req,
                               plane_res[plane].plane->plane_id, "SRC_X", src_x << 16))
    return -EINVAL;
  if (atomic_add_prop_to_plane(plane_res, atomic_req,
                               plane_res[plane].plane->plane_id, "SRC_Y", src_y << 16))
    return -EINVAL;
  if (atomic_add_prop_to_plane(plane_res, atomic_req,
                               plane_res[plane].plane->plane_id, "SRC_W", src_w << 16))
    return -EINVAL;
  if (atomic_add_prop_to_plane(plane_res, atomic_req,
                               plane_res[plane].plane->plane_id, "SRC_H", src_h << 16))
    return -EINVAL;
  if (atomic_add_prop_to_plane(plane_res, atomic_req,
                               plane_res[plane].plane->plane_id, "CRTC_X", crtc_x))
    return -EINVAL;
  if (atomic_add_prop_to_plane(plane_res, atomic_req,
                               plane_res[plane].plane->plane_id, "CRTC_Y", crtc_y))
    return -EINVAL;
  if (atomic_add_prop_to_plane(plane_res, atomic_req,
                               plane_res[plane].plane->plane_id, "CRTC_W", crtc_w))
    return -EINVAL;
  if (atomic_add_prop_to_plane(plane_res, atomic_req,
                               plane_res[plane].plane->plane_id, "CRTC_H", crtc_h))
    return -EINVAL;
  if (atomic_add_prop_to_plane(plane_res, atomic_req,
                               plane_res[plane].plane->plane_id, "CRTC_ID",
                               main_monitor_crtc->crtc_id))
    return -EINVAL;

  return 0;
}

static int teardown_pipeline(drmModeAtomicReqPtr atomic_req) {
  uint32_t i, prop_id;
  int ret;

  add_prop(&conn_res, connector, Connector, main_monitor_connector->connector_id, "CRTC_ID", 0);
  add_prop(&crtc_res, crtc, Crtc, main_monitor_crtc->crtc_id, "MODE_ID", 0);
  add_prop(&crtc_res, crtc, Crtc, main_monitor_crtc->crtc_id, "ACTIVE", 0);

  for (i = 0; i < number_of_lms; i++) {
    ret = atomic_add_prop_to_plane(plane_res, atomic_req,
                                   plane_res[i].plane->plane_id, "CRTC_ID", 0);
    if (ret < 0) {
      printf("Failed to tear down plane %d\n", i);
      return ret;
    }

    if (drmModeAtomicAddProperty(atomic_req, plane_res[i].plane->plane_id, fb_prop_id, 0) < 0) {
      printf("Failed to add property for plane_id=%d\n", plane_res[i].plane->plane_id);
      return -EINVAL;
    }
  }

  return 0;
}

static int drm_disable_crtc(drmModeAtomicReqPtr atomic_req) {
  return teardown_pipeline(atomic_req);
}

static int setup_pipeline(drmModeAtomicReqPtr atomic_req) {
  uint32_t i, prop_id;
  int ret;

  for (i = 0; i < number_of_lms; i++) {
    add_prop(&conn_res, connector, Connector, main_monitor_connector->connector_id,
             "CRTC_ID", main_monitor_crtc->crtc_id);
    add_prop(&crtc_res, crtc, Crtc, main_monitor_crtc->crtc_id, "MODE_ID", crtc_res.mode_blob_id);
    add_prop(&crtc_res, crtc, Crtc, main_monitor_crtc->crtc_id, "ACTIVE", 1);
  }

  for (i = 0; i < number_of_lms; i++) {
    ret = atomic_populate_plane(i, atomic_req);
    if (ret < 0) {
      printf("Error populating plane_id = %d\n", plane_res[i].plane->plane_id);
      return ret;
    }
  }

  return 0;
}

static int drm_enable_crtc(drmModeAtomicReqPtr atomic_req) {
  return setup_pipeline(atomic_req);
}

static void drm_blank(minui_backend* backend __unused, bool blank) {
  int ret = 0;

  if (blank == current_blank_state)
    return;

  drmModeAtomicReqPtr atomic_req = drmModeAtomicAlloc();
  if (!atomic_req) {
    printf("Atomic Alloc failed\n");
    return;
  }

  if (blank)
    ret = drm_disable_crtc(atomic_req);
  else
    ret = drm_enable_crtc(atomic_req);

  if (!ret)
    ret = drmModeAtomicCommit(drm_fd, atomic_req, DRM_MODE_ATOMIC_ALLOW_MODESET, NULL);

  if (!ret) {
    printf("Atomic Commit succeed\n");
    current_blank_state = blank;
  } else {
    printf("Atomic Commit failed, rc = %d\n", ret);
  }

  drmModeAtomicFree(atomic_req);
}

static void drm_destroy_surface(struct drm_surface *surface) {
  if (!surface) return;

  if (surface->base.data) {
    munmap(surface->base.data, surface->base.row_bytes * surface->base.height);
  }

  if (surface->fb_id) {
    int ret = drmModeRmFB(drm_fd, surface->fb_id);
    if (ret) {
      printf("drmModeRmFB failed ret=%d\n", ret);
    }
  }

  if (surface->handle) {
    drm_gem_close gem_close = {};
    gem_close.handle = surface->handle;
    int ret = drmIoctl(drm_fd, DRM_IOCTL_GEM_CLOSE, &gem_close);
    if (ret) {
      printf("DRM_IOCTL_GEM_CLOSE failed ret=%d\n", ret);
    }
  }

  free(surface);
}

static int drm_format_to_bpp(uint32_t format) {
  switch (format) {
    case DRM_FORMAT_ABGR8888:
    case DRM_FORMAT_BGRA8888:
    case DRM_FORMAT_RGBX8888:
    case DRM_FORMAT_RGBA8888:
    case DRM_FORMAT_BGRX8888:
    case DRM_FORMAT_XBGR8888:
    case DRM_FORMAT_ARGB8888:
    case DRM_FORMAT_XRGB8888:
      return 32;
    case DRM_FORMAT_RGB565:
      return 16;
    default:
      printf("Unknown format %d\n", format);
      return 32;
  }
}

static drm_surface *drm_create_surface(int width, int height) {
  uint32_t format;
  __u32 base_format;
  int ret;

  drm_surface* surface = static_cast<drm_surface*>(calloc(1, sizeof(*surface)));
  if (!surface) {
    printf("Can't allocate memory\n");
    return nullptr;
  }

#if defined(RECOVERY_ABGR)
  format = DRM_FORMAT_RGBA8888;
  base_format = GGL_PIXEL_FORMAT_RGBA_8888;
#elif defined(RECOVERY_BGRA)
  format = DRM_FORMAT_ARGB8888;
  base_format = GGL_PIXEL_FORMAT_RGBA_8888;
#elif defined(RECOVERY_RGBA)
  format = DRM_FORMAT_ABGR8888;
  base_format = GGL_PIXEL_FORMAT_BGRA_8888;
#elif defined(RECOVERY_RGBX)
  format = DRM_FORMAT_XBGR8888;
  base_format = GGL_PIXEL_FORMAT_RGBA_8888;
#else
  format = DRM_FORMAT_RGB565;
  base_format = GGL_PIXEL_FORMAT_BGRA_8888;
#endif

  drm_mode_create_dumb create_dumb = {};
  create_dumb.height = height;
  create_dumb.width = width;
  create_dumb.bpp = drm_format_to_bpp(format);
  create_dumb.flags = 0;

  ret = drmIoctl(drm_fd, DRM_IOCTL_MODE_CREATE_DUMB, &create_dumb);
  if (ret) {
    printf("DRM_IOCTL_MODE_CREATE_DUMB failed ret=%d\n", ret);
    drm_destroy_surface(surface);
    return nullptr;
  }
  surface->handle = create_dumb.handle;

  uint32_t handles[4], pitches[4], offsets[4];
  handles[0] = surface->handle;
  pitches[0] = create_dumb.pitch;
  offsets[0] = 0;

  ret = drmModeAddFB2(drm_fd, width, height,
                      format, handles, pitches, offsets,
                      &(surface->fb_id), 0);
  if (ret) {
    printf("drmModeAddFB2 failed ret=%d\n", ret);
    drm_destroy_surface(surface);
    return nullptr;
  }

  struct drm_mode_map_dumb map_dumb = {};
  map_dumb.handle = create_dumb.handle;
  ret = drmIoctl(drm_fd, DRM_IOCTL_MODE_MAP_DUMB, &map_dumb);
  if (ret) {
    printf("DRM_IOCTL_MODE_MAP_DUMB failed ret=%d\n", ret);
    drm_destroy_surface(surface);
    return nullptr;
  }

  surface->base.height = height;
  surface->base.width = width;
  surface->base.row_bytes = create_dumb.pitch;
  surface->base.pixel_bytes = create_dumb.bpp / 8;
  surface->base.format = base_format;
  surface->base.data = (unsigned char*)mmap(
      nullptr,
      surface->base.height * surface->base.row_bytes,
      PROT_READ | PROT_WRITE, MAP_SHARED,
      drm_fd, map_dumb.offset);
  if (surface->base.data == MAP_FAILED) {
    surface->base.data = nullptr;
    printf("mmap() failed\n");
    drm_destroy_surface(surface);
    return nullptr;
  }

  return surface;
}

static drmModeCrtc *find_crtc_for_connector_excluding(int fd,
                                                      drmModeRes *resources,
                                                      drmModeConnector *connector,
                                                      uint32_t exclude_crtc_id,
                                                      int *out_crtc_index) {
  drmModeEncoder *encoder = connector->encoder_id ? drmModeGetEncoder(fd, connector->encoder_id) : nullptr;
  if (encoder && encoder->crtc_id && encoder->crtc_id != exclude_crtc_id) {
    uint32_t cid = encoder->crtc_id;
    drmModeFreeEncoder(encoder);
    for (int j = 0; j < resources->count_crtcs; j++) {
      if (resources->crtcs[j] == cid) {
        if (out_crtc_index) *out_crtc_index = j;
        return drmModeGetCrtc(fd, cid);
      }
    }
  } else if (encoder) {
    drmModeFreeEncoder(encoder);
  }

  for (int i = 0; i < connector->count_encoders; i++) {
    encoder = drmModeGetEncoder(fd, connector->encoders[i]);
    if (!encoder) continue;
    for (int j = 0; j < resources->count_crtcs; j++) {
      if (!(encoder->possible_crtcs & (1u << j))) continue;
      if (resources->crtcs[j] == exclude_crtc_id) continue;
      uint32_t cid = resources->crtcs[j];
      drmModeFreeEncoder(encoder);
      if (out_crtc_index) *out_crtc_index = j;
      return drmModeGetCrtc(fd, cid);
    }
    drmModeFreeEncoder(encoder);
  }
  return nullptr;
}

static drmModeConnector *find_first_connected_connector(int fd, drmModeRes *resources) {
  for (int i = 0; i < resources->count_connectors; i++) {
    drmModeConnector* connector = drmModeGetConnector(fd, resources->connectors[i]);
    if (connector) {
      if ((connector->count_modes > 0) && (connector->connection == DRM_MODE_CONNECTED))
        return connector;
      drmModeFreeConnector(connector);
    }
  }
  return nullptr;
}

static bool b6q_is_cursor_plane(int fd, drmModeObjectProperties *props, drmModePropertyRes **props_info) {
  (void)fd;
  for (uint32_t j = 0; j < props->count_props; ++j) {
    if (!strcmp(props_info[j]->name, "type") && props->prop_values[j] == 2) {
      return true;
    }
  }
  return false;
}

static bool b6q_init_display(drmModeRes *res, drmModeConnector *connector,
                             uint32_t exclude_crtc_id, struct B6qDrmDisplay *out) {
  memset(out, 0, sizeof(*out));
  if (!connector || connector->count_modes <= 0) return false;

  uint32_t selected_mode = 0;
  for (int m = 0; m < connector->count_modes; m++) {
    if (connector->modes[m].type & DRM_MODE_TYPE_PREFERRED) {
      selected_mode = m;
      break;
    }
  }

  int crtc_index = 0;
  drmModeCrtc *crtc = find_crtc_for_connector_excluding(drm_fd, res, connector, exclude_crtc_id, &crtc_index);
  if (!crtc) return false;

  crtc->mode = connector->modes[selected_mode];
  out->connector = connector;
  out->crtc = crtc;
  out->crtc_index = crtc_index;
  out->width = crtc->mode.hdisplay;
  out->height = crtc->mode.vdisplay;
  out->number_of_lms = DEFAULT_NUM_LMS;

  out->crtc_res.props = drmModeObjectGetProperties(drm_fd, crtc->crtc_id, DRM_MODE_OBJECT_CRTC);
  if (!out->crtc_res.props) return false;
  out->crtc_res.props_info = static_cast<drmModePropertyRes **>(
      calloc(out->crtc_res.props->count_props, sizeof(*out->crtc_res.props_info)));
  if (!out->crtc_res.props_info) return false;
  for (uint32_t j = 0; j < out->crtc_res.props->count_props; ++j)
    out->crtc_res.props_info[j] = drmModeGetProperty(drm_fd, out->crtc_res.props->props[j]);

  out->conn_res.props = drmModeObjectGetProperties(drm_fd, connector->connector_id, DRM_MODE_OBJECT_CONNECTOR);
  if (!out->conn_res.props) return false;
  out->conn_res.props_info = static_cast<drmModePropertyRes **>(
      calloc(out->conn_res.props->count_props, sizeof(*out->conn_res.props_info)));
  if (!out->conn_res.props_info) return false;
  for (uint32_t j = 0; j < out->conn_res.props->count_props; ++j) {
    out->conn_res.props_info[j] = drmModeGetProperty(drm_fd, out->conn_res.props->props[j]);
    if (!strcmp(out->conn_res.props_info[j]->name, "mode_properties")) {
      out->number_of_lms = get_topology_lm_number(drm_fd, out->conn_res.props->prop_values[j]);
      printf("display %dx%d lms=%u\n", out->width, out->height, out->number_of_lms);
    }
  }

  drmModePlaneRes *plane_options = drmModeGetPlaneResources(drm_fd);
  if (!plane_options || !plane_options->planes) return false;

  uint32_t picked = 0;
  for (uint32_t i = 0; i < plane_options->count_planes && picked < out->number_of_lms; ++i) {
    drmModePlane *p = drmModeGetPlane(drm_fd, plane_options->planes[i]);
    if (!p) continue;
    if (!(p->possible_crtcs & (1u << crtc_index))) {
      drmModeFreePlane(p);
      continue;
    }
    drmModeObjectProperties *pprops = drmModeObjectGetProperties(drm_fd, p->plane_id, DRM_MODE_OBJECT_PLANE);
    if (!pprops) {
      drmModeFreePlane(p);
      continue;
    }
    drmModePropertyRes **pinfo = static_cast<drmModePropertyRes **>(
        calloc(pprops->count_props, sizeof(*pinfo)));
    for (uint32_t j = 0; j < pprops->count_props; ++j)
      pinfo[j] = drmModeGetProperty(drm_fd, pprops->props[j]);

    if (b6q_is_cursor_plane(drm_fd, pprops, pinfo)) {
      for (uint32_t j = 0; j < pprops->count_props; ++j) drmModeFreeProperty(pinfo[j]);
      free(pinfo);
      drmModeFreeObjectProperties(pprops);
      drmModeFreePlane(p);
      continue;
    }

    out->plane_res[picked].plane = p;
    out->plane_res[picked].props = pprops;
    out->plane_res[picked].props_info = pinfo;
    picked++;
  }
  drmModeFreePlaneResources(plane_options);

  if (picked < out->number_of_lms) {
    printf("Not enough compatible planes (%u < %u) for %dx%d\n",
           picked, out->number_of_lms, out->width, out->height);
    return false;
  }

  if (drmModeCreatePropertyBlob(drm_fd, &crtc->mode, sizeof(drmModeModeInfo),
                                &out->crtc_res.mode_blob_id)) {
    printf("failed to create mode blob for %dx%d\n", out->width, out->height);
    return false;
  }

  out->fb_prop_id = find_plane_prop_id(out->plane_res[0].plane->plane_id, "FB_ID", out->plane_res);
  out->surfaces[0] = drm_create_surface(out->width, out->height);
  out->surfaces[1] = drm_create_surface(out->width, out->height);
  if (!out->surfaces[0] || !out->surfaces[1]) {
    drm_destroy_surface(out->surfaces[0]);
    drm_destroy_surface(out->surfaces[1]);
    out->surfaces[0] = out->surfaces[1] = nullptr;
    return false;
  }

  out->valid = true;
  return true;
}

static void update_plane_fb() {
  uint32_t i, prop_id;
  drmModeAtomicReqPtr atomic_req = drmModeAtomicAlloc();
  if (!atomic_req) {
    printf("Atomic Alloc failed. Could not update fb_id\n");
    return;
  }

  add_prop(&conn_res, connector, Connector, main_monitor_connector->connector_id,
           "CRTC_ID", main_monitor_crtc->crtc_id);

  for (i = 0; i < number_of_lms; i++)
    drmModeAtomicAddProperty(atomic_req, plane_res[i].plane->plane_id,
                             fb_prop_id, drm_surfaces[current_buffer]->fb_id);

  int32_t ret = drmModeAtomicCommit(drm_fd, atomic_req, DRM_MODE_ATOMIC_ALLOW_MODESET, NULL);
  drmModeAtomicFree(atomic_req);

  if (ret)
    printf("Atomic commit failed ret=%d\n", ret);
}

static void b6q_copy_to_active_surface(drm_surface *dst_surf) {
  if (!dst_surf || !dst_surf->base.data || !draw_buf || !draw_buf->data) return;

  if (dst_surf->base.width == draw_buf->width && dst_surf->base.height == draw_buf->height) {
    memcpy(dst_surf->base.data, draw_buf->data, draw_buf->height * draw_buf->row_bytes);
    return;
  }

  int src_w = draw_buf->width;
  int src_h = draw_buf->height;
  int dst_w = dst_surf->base.width;
  int dst_h = dst_surf->base.height;
  int src_stride = draw_buf->row_bytes / 4;
  int dst_stride = dst_surf->base.row_bytes / 4;
  const uint32_t *src = reinterpret_cast<const uint32_t *>(draw_buf->data);
  uint32_t *dst = reinterpret_cast<uint32_t *>(dst_surf->base.data);

  for (int dy = 0; dy < dst_h; ++dy) {
    int sy = (dy * src_h) / dst_h;
    const uint32_t *srow = src + sy * src_stride;
    uint32_t *drow = dst + dy * dst_stride;
    for (int dx = 0; dx < dst_w; ++dx) {
      int sx = (dx * src_w) / dst_w;
      drow[dx] = srow[sx];
    }
  }
}

static GRSurface* drm_init(minui_backend* backend __unused) {
  drmModeRes* res = nullptr;

  for (int i = 0; i < DRM_MAX_MINOR; i++) {
    char* dev_name;
    int ret = asprintf(&dev_name, DRM_DEV_NAME, DRM_DIR_NAME, i);
    if (ret < 0) continue;

    drm_fd = open(dev_name, O_RDWR, 0);
    free(dev_name);
    if (drm_fd < 0) continue;

    uint64_t cap = 0;
    ret = drmGetCap(drm_fd, DRM_CAP_DUMB_BUFFER, &cap);
    if (ret || cap == 0) {
      close(drm_fd);
      continue;
    }
    res = drmModeGetResources(drm_fd);
    if (!res) {
      close(drm_fd);
      continue;
    }

    if (res->count_crtcs > 0 && res->count_connectors > 0) {
      drmModeConnector *tmp = find_first_connected_connector(drm_fd, res);
      if (tmp) {
        drmModeFreeConnector(tmp);
        break;
      }
    }

    drmModeFreeResources(res);
    close(drm_fd);
    res = nullptr;
  }

  if (drm_fd < 0 || res == nullptr) {
    perror("cannot find/open a drm device");
    return nullptr;
  }

  drmSetClientCap(drm_fd, DRM_CLIENT_CAP_UNIVERSAL_PLANES, 1);
  drmSetClientCap(drm_fd, DRM_CLIENT_CAP_ATOMIC, 1);

  drmModeConnector *dsi_conns[2] = {nullptr, nullptr};
  int dsi_count = 0;
  for (int i = 0; i < res->count_connectors && dsi_count < 2; i++) {
    drmModeConnector *c = drmModeGetConnector(drm_fd, res->connectors[i]);
    if (!c) continue;
    if (c->connector_type == DRM_MODE_CONNECTOR_DSI &&
        c->connection == DRM_MODE_CONNECTED &&
        c->count_modes > 0) {
      dsi_conns[dsi_count++] = c;
    } else {
      drmModeFreeConnector(c);
    }
  }

  if (dsi_count == 0) {
    printf("No connected DSI connector found\n");
    drmModeFreeResources(res);
    close(drm_fd);
    return nullptr;
  }

  drmModeConnector *inner_conn = dsi_conns[0];
  drmModeConnector *outer_conn = (dsi_count > 1) ? dsi_conns[1] : nullptr;
  if (outer_conn && outer_conn->modes[0].hdisplay > inner_conn->modes[0].hdisplay) {
    inner_conn = dsi_conns[1];
    outer_conn = dsi_conns[0];
  }

  if (!b6q_init_display(res, inner_conn, 0, &inner_disp)) {
    printf("Failed to init inner display\n");
    drmModeFreeResources(res);
    close(drm_fd);
    return nullptr;
  }

  if (outer_conn) {
    if (!b6q_init_display(res, outer_conn, inner_disp.crtc->crtc_id, &outer_disp)) {
      printf("Warning: failed to init outer display, continuing with inner only\n");
      outer_disp.valid = false;
    }
  }

  b6q_drm_folded = outer_disp.valid ? b6q_read_folded_state() : false;
  if (outer_disp.valid) {
    struct B6qDrmDisplay *inactive = b6q_drm_folded ? &inner_disp : &outer_disp;
    if (inactive->connector && inactive->connector->encoder_id != 0) {
      b6q_activate_display_state(inactive);
      current_blank_state = false;
      drm_blank(nullptr, true);
    }
  }
  drmModeFreeResources(res);

  draw_buf = (GRSurface *)malloc(sizeof(GRSurface));
  if (!draw_buf) {
    printf("failed to alloc draw_buf\n");
    return nullptr;
  }

  memcpy(draw_buf, &inner_disp.surfaces[0]->base, sizeof(GRSurface));
  draw_buf->data = (unsigned char *)calloc(draw_buf->height * draw_buf->row_bytes, 1);
  if (!draw_buf->data) {
    printf("failed to alloc draw_buf surface\n");
    free(draw_buf);
    draw_buf = nullptr;
    return nullptr;
  }

  current_buffer = 0;
  b6q_activate_display_state(b6q_drm_folded ? &outer_disp : &inner_disp);
  b6q_apply_backlights(b6q_drm_folded);
  current_blank_state = true;
  drm_blank(nullptr, false);

  return draw_buf;
}

static GRSurface* drm_flip(minui_backend* backend __unused) {
  bool want_folded = outer_disp.valid ? b6q_read_folded_state() : false;
  if (want_folded != b6q_drm_folded) {
    bool was_blanked = current_blank_state;
    if (!was_blanked) {
      drm_blank(nullptr, true);
    }
    b6q_drm_folded = want_folded;
    b6q_activate_display_state(b6q_drm_folded ? &outer_disp : &inner_disp);
    b6q_copy_to_active_surface(drm_surfaces[current_buffer]);
    b6q_apply_backlights(b6q_drm_folded);
    if (!was_blanked) {
      drm_blank(nullptr, false);
    }
    current_buffer = 1 - current_buffer;
    return draw_buf;
  }

  b6q_copy_to_active_surface(drm_surfaces[current_buffer]);
  update_plane_fb();
  current_buffer = 1 - current_buffer;
  return draw_buf;
}

static void drm_exit(minui_backend* backend __unused) {
  drm_blank(nullptr, true);
  if (inner_disp.valid) {
    drmModeDestroyPropertyBlob(drm_fd, inner_disp.crtc_res.mode_blob_id);
    drm_destroy_surface(inner_disp.surfaces[0]);
    drm_destroy_surface(inner_disp.surfaces[1]);
  }
  if (outer_disp.valid) {
    drmModeDestroyPropertyBlob(drm_fd, outer_disp.crtc_res.mode_blob_id);
    drm_destroy_surface(outer_disp.surfaces[0]);
    drm_destroy_surface(outer_disp.surfaces[1]);
  }
  close(drm_fd);
  drm_fd = -1;
}

static minui_backend drm_backend = {
    .init = drm_init,
    .flip = drm_flip,
    .blank = drm_blank,
    .exit = drm_exit,
};

minui_backend* open_drm() {
  return &drm_backend;
}
"""
    src = src[:idx] + replacement
    path.write_text(src, encoding="utf-8")
    print(f"Patched {path}")


def patch_twrp_functions(path: pathlib.Path) -> None:
    src = path.read_text(encoding="utf-8")
    if "/tmp/.b6q_brightness" in src:
        print(f"{path} already patched.")
        return

    anchor = """int TWFunc::Set_Brightness(std::string brightness_value)
{
\tint result = -1;
\tstd::string secondary_brightness_file;

\tif (DataManager::GetIntValue("tw_has_brightnesss_file")) {
\t\tLOGINFO("TWFunc::Set_Brightness: Setting brightness control to %s\\n", brightness_value.c_str());
\t\tresult = TWFunc::write_to_file(DataManager::GetStrValue("tw_brightness_file"), brightness_value);
\t\tDataManager::GetValue("tw_secondary_brightness_file", secondary_brightness_file);
\t\tif (!secondary_brightness_file.empty()) {
\t\t\tLOGINFO("TWFunc::Set_Brightness: Setting secondary brightness control to %s\\n", brightness_value.c_str());
\t\t\tTWFunc::write_to_file(secondary_brightness_file, brightness_value);
\t\t}
\t}
\treturn result ? 0 : -1;
}"""
    if anchor not in src:
        raise SystemExit(f"ERROR: Set_Brightness anchor not found in {path}")

    repl = """int TWFunc::Set_Brightness(std::string brightness_value)
{
\tint result = -1;
\tstd::string secondary_brightness_file;

\tif (DataManager::GetIntValue("tw_has_brightnesss_file")) {
\t\tint bval = atoi(brightness_value.c_str());
\t\tif (bval > 0) {
\t\t\tTWFunc::write_to_file("/tmp/.b6q_brightness", brightness_value);
\t\t}
\t\tstd::string flip_state;
\t\tbool folded = (TWFunc::read_file("/sys/class/sec/hall_ic/flip_status", flip_state) == 0 &&
\t\t               !flip_state.empty() && flip_state[0] == '0');
\t\tif (folded) {
\t\t\tint sub_val = (bval <= 0) ? 0 : (bval * 7650) / 12750;
\t\t\tif (bval > 0 && sub_val < 200) sub_val = 200;
\t\t\tif (sub_val > 7650) sub_val = 7650;
\t\t\tTWFunc::write_to_file("/sys/class/backlight/panel0-backlight/brightness", "0");
\t\t\tresult = TWFunc::write_to_file("/sys/class/backlight/panel1-backlight/brightness", std::to_string(sub_val));
\t\t} else {
\t\t\tTWFunc::write_to_file("/sys/class/backlight/panel1-backlight/brightness", "0");
\t\t\tLOGINFO("TWFunc::Set_Brightness: Setting brightness control to %s\\n", brightness_value.c_str());
\t\t\tresult = TWFunc::write_to_file(DataManager::GetStrValue("tw_brightness_file"), brightness_value);
\t\t}
\t\tDataManager::GetValue("tw_secondary_brightness_file", secondary_brightness_file);
\t\tif (!secondary_brightness_file.empty()) {
\t\t\tLOGINFO("TWFunc::Set_Brightness: Setting secondary brightness control to %s\\n", brightness_value.c_str());
\t\t\tTWFunc::write_to_file(secondary_brightness_file, brightness_value);
\t\t}
\t}
\treturn result ? 0 : -1;
}"""
    src = src.replace(anchor, repl, 1)
    path.write_text(src, encoding="utf-8")
    print(f"Patched {path}")


def patch_gui(path: pathlib.Path) -> None:
    src = path.read_text(encoding="utf-8")
    if "b6q_last_fold" in src:
        print(f"{path} already patched.")
        return

    anchor = "\t\tif (!gForceRender.get_value())"
    if anchor not in src:
        raise SystemExit(f"ERROR: gForceRender anchor not found in {path}")

    repl = """\t\t{
\t\t\tstatic int b6q_last_fold = -1;
\t\t\tstd::string flip_val;
\t\t\tif (TWFunc::read_file("/sys/class/sec/hall_ic/flip_status", flip_val) == 0 && !flip_val.empty()) {
\t\t\t\tint f = (flip_val[0] == '0') ? 1 : 0;
\t\t\t\tif (b6q_last_fold != -1 && b6q_last_fold != f) {
\t\t\t\t\tblankTimer.resetTimerAndUnblank();
\t\t\t\t\tgForceRender.set_value(1);
\t\t\t\t}
\t\t\t\tb6q_last_fold = f;
\t\t\t}
\t\t}

\t\tif (!gForceRender.get_value())"""
    src = src.replace(anchor, repl, 1)
    path.write_text(src, encoding="utf-8")
    print(f"Patched {path}")


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit(f"Usage: {sys.argv[0]} <path/to/bootable/recovery>")
    rec_dir = pathlib.Path(sys.argv[1])
    patch_events(rec_dir / "minuitwrp" / "events.cpp")
    patch_graphics_drm(rec_dir / "minuitwrp" / "graphics_drm.cpp")
    patch_twrp_functions(rec_dir / "twrp-functions.cpp")
    patch_gui(rec_dir / "gui" / "gui.cpp")


if __name__ == "__main__":
    main()
