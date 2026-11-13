// SPDX-License-Identifier: GPL-2.0-or-later
/*
 * Doom on the Xiegu X6100: the doomgeneric platform layer, and the system's whole userland.
 *
 * It runs as /sbin/init on a root filesystem of its own, with the kernel of a system already on
 * the card (all the drivers it needs are built in: the DRM framebuffer with the ST7701S panel,
 * the key matrix, the rotary encoders, devtmpfs). Picture: Doom's 320x200 scaled to 640x480 (the
 * original 4:3), centred on the landscape 800x480 screen and turned into the portrait panel's
 * framebuffer as Linux's fbcon=rotate:3 does. Input: the front keys and the three knobs.
 * Leaving Doom, or an error, restarts the radio into the boot menu; POWER switches it off.
 *
 * Based on doomgeneric_linuxvt.c (doomgeneric, GPL-2.0).
 */
#include "doomkeys.h"
#include "m_argv.h"
#include "doomgeneric.h"

/* Linux's input-event-codes.h and doomkeys.h share names: Doom's values are taken here, before
 * the Linux headers redefine them */
enum {
	DK_ENTER = KEY_ENTER, DK_ESCAPE = KEY_ESCAPE, DK_TAB = KEY_TAB,
	DK_UP = KEY_UPARROW, DK_DOWN = KEY_DOWNARROW, DK_LEFT = KEY_LEFTARROW, DK_RIGHT = KEY_RIGHTARROW,
	DK_FIRE = KEY_FIRE, DK_USE = KEY_USE, DK_STRAFE_L = KEY_STRAFE_L, DK_STRAFE_R = KEY_STRAFE_R,
	DK_RSHIFT = KEY_RSHIFT,
};
#undef KEY_RSHIFT
#undef KEY_TAB
#undef KEY_ENTER
#undef KEY_BACKSPACE
#undef KEY_MINUS
#undef KEY_F1
#undef KEY_F2
#undef KEY_F3
#undef KEY_F4
#undef KEY_F5
#undef KEY_F6
#undef KEY_F7
#undef KEY_F8
#undef KEY_F9
#undef KEY_F10
#undef KEY_F11
#undef KEY_F12

#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <linux/fb.h>
#include <linux/input.h>
#include <linux/kd.h>
#include <linux/reboot.h>
#include <poll.h>
#include <signal.h>
#include <stdarg.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <sys/mount.h>
#include <sys/reboot.h>
#include <sys/stat.h>
#include <sys/time.h>
#include <time.h>
#include <unistd.h>

#define OUT_W   640             /* 320x200 shown at 4:3 */
#define OUT_H   480
#define LAND_W  800             /* the screen, as the radio is held */
#define LAND_H  480
#define MAX_DEVS 16
#define QSIZE   64

/* The X6100's front keys: BTN_TRIGGER_HAPPY1..30 from the key matrix (OpenX6X00 src/front_keys.c) */
#define HAPPY(n) (BTN_TRIGGER_HAPPY1 + (n) - 1)

static uint8_t *fb;
static int fb_fd = -1, tty_fd = -1;
static unsigned fb_w, fb_h, fb_stride, fb_bpp;
static struct fb_var_screeninfo vinfo;
static uint16_t map_x[LAND_W], map_y[LAND_H];  /* landscape pixel -> Doom pixel (0xffff: border) */
static int rotate = 3;                          /* 3: as fbcon=rotate:3; 1: the other way; 0: none */

static int in_fd[MAX_DEVS], n_in;
static struct pollfd pfd[MAX_DEVS];
static unsigned short queue[QSIZE];
static unsigned q_w, q_r;
static struct timespec t0;

/* A knob turned: its key held for a while per detent, then let go */
struct pulse {
	unsigned char key;   /* the key now held, 0 for none */
	uint32_t until;      /* when to let it go */
};
static struct pulse pulses[3];   /* main knob, VOL, MFK */
static int weapon = 1;

static uint32_t now_ms(void)
{
	struct timespec t;
	clock_gettime(CLOCK_MONOTONIC, &t);
	return (uint32_t)((t.tv_sec - t0.tv_sec) * 1000 + (t.tv_nsec - t0.tv_nsec) / 1000000);
}

static void push(int pressed, unsigned char key)
{
	queue[q_w] = (unsigned short)((pressed << 8) | key);
	q_w = (q_w + 1) % QSIZE;
	if (q_w == q_r)                       /* full: the oldest goes */
		q_r = (q_r + 1) % QSIZE;
}

/* ------------------------------------------------------------------------------------------ */
/* Leaving: back to the boot menu, or off                                                    */
/* ------------------------------------------------------------------------------------------ */
static void text_mode(void)
{
	if (tty_fd >= 0)
		ioctl(tty_fd, KDSETMODE, KD_TEXT);
}

static void leave(int cmd)
{
	text_mode();
	sync();
	if (getpid() == 1)
		reboot(cmd);
	exit(0);
}

static void say(const char *fmt, ...)
{
	va_list ap;
	FILE *f = fopen("/dev/tty0", "w");
	if (!f)
		f = stderr;
	va_start(ap, fmt);
	vfprintf(f, fmt, ap);
	va_end(ap);
	fflush(f);
	if (f != stderr)
		fclose(f);
}

/* Doom's exit (I_Quit, I_Error): its message stays on the screen a moment, then the menu again */
static void at_exit(void)
{
	text_mode();
	if (getpid() == 1) {
		say("\n  Doom: koniec. Restart do menu za 5 s...\n");
		sleep(5);
		sync();
		reboot(RB_AUTOBOOT);
	}
}

static void on_signal(int sig)
{
	(void)sig;
	leave(RB_AUTOBOOT);
}

/* ------------------------------------------------------------------------------------------ */
/* Picture                                                                                    */
/* ------------------------------------------------------------------------------------------ */
static void setup_maps(void)
{
	int x0 = (LAND_W - OUT_W) / 2, y0 = (LAND_H - OUT_H) / 2;
	for (int x = 0; x < LAND_W; x++)
		map_x[x] = (x < x0 || x >= x0 + OUT_W) ? 0xffff : (uint16_t)((x - x0) * DOOMGENERIC_RESX / OUT_W);
	for (int y = 0; y < LAND_H; y++)
		map_y[y] = (y < y0 || y >= y0 + OUT_H) ? 0xffff : (uint16_t)((y - y0) * DOOMGENERIC_RESY / OUT_H);
}

static inline void put(unsigned fx, unsigned fy, uint32_t p)
{
	uint8_t *d = fb + fy * fb_stride + fx * fb_bpp;
	if (fb_bpp == 4) {
		*(uint32_t *)d = p;   /* i_video.c packs it with the framebuffer's offsets */
	} else {                                  /* 16 bpp: RGB565 from the 32-bit pixel */
		uint32_t r = (p >> vinfo.red.offset) & 0xff, g = (p >> vinfo.green.offset) & 0xff,
		         b = (p >> vinfo.blue.offset) & 0xff;
		*(uint16_t *)d = (uint16_t)(((r & 0xf8) << 8) | ((g & 0xfc) << 3) | (b >> 3));
	}
}

static void draw(void);
static void test_dump(void);

void DG_DrawFrame(void)
{
	draw();
	test_dump();
}

static void draw(void)
{
	const uint32_t *src = (const uint32_t *)DG_ScreenBuffer;
	if (rotate == 3 || rotate == 1) {
		/* portrait framebuffer: one of its rows is one landscape column */
		for (unsigned lx = 0; lx < LAND_W && lx < fb_h; lx++) {
			unsigned fy = rotate == 3 ? (fb_h - 1 - lx) : lx;
			uint16_t sx = map_x[lx];
			for (unsigned ly = 0; ly < LAND_H && ly < fb_w; ly++) {
				unsigned fx = rotate == 3 ? ly : (fb_w - 1 - ly);
				uint16_t sy = map_y[ly];
				uint32_t p = (sx == 0xffff || sy == 0xffff) ? 0 : src[sy * DOOMGENERIC_RESX + sx];
				put(fx, fy, p);
			}
		}
	} else {
		for (unsigned ly = 0; ly < LAND_H && ly < fb_h; ly++) {
			uint16_t sy = map_y[ly];
			for (unsigned lx = 0; lx < LAND_W && lx < fb_w; lx++) {
				uint16_t sx = map_x[lx];
				put(lx, ly, (sx == 0xffff || sy == 0xffff) ? 0 : src[sy * DOOMGENERIC_RESX + sx]);
			}
		}
	}
}

/* ------------------------------------------------------------------------------------------ */
/* Input                                                                                      */
/* ------------------------------------------------------------------------------------------ */
static unsigned char key_for(unsigned code)
{
	switch (code) {
	case HAPPY(13): return DK_FIRE;       /* F1 */
	case HAPPY(4):  return DK_FIRE;       /* PTT */
	case HAPPY(14): return DK_USE;        /* F2: doors, switches */
	case HAPPY(15): return DK_ENTER;      /* F3 */
	case HAPPY(19): return DK_STRAFE_L;   /* F4 */
	case HAPPY(20): return DK_STRAFE_R;   /* F5 */
	case HAPPY(6):  return DK_UP;         /* BAND up: forward */
	case HAPPY(5):  return DK_DOWN;       /* BAND down: back */
	case HAPPY(8):  return DK_LEFT;       /* DFN */
	case HAPPY(9):  return DK_RIGHT;      /* DFL */
	case HAPPY(1):  return DK_ESCAPE;     /* GEN: the menu */
	case HAPPY(2):  return DK_TAB;        /* APP: the map */
	case HAPPY(3):  return 'y';           /* KEY: yes */
	case HAPPY(7):  return 'n';           /* MSG: no */
	case HAPPY(10): return DK_RSHIFT;     /* AM: run */
	case HAPPY(21): return DK_ESCAPE;     /* VOL pressed */
	case HAPPY(27): return DK_ENTER;      /* MFK pressed */
	default:        return 0;
	}
}

static void knob(int axis, int value)
{
	struct pulse *p = &pulses[axis];
	unsigned char key;
	if (axis == 2) {                      /* MFK: weapons 1..7 */
		weapon += value > 0 ? 1 : -1;
		if (weapon < 1) weapon = 7;
		if (weapon > 7) weapon = 1;
		push(1, (unsigned char)('0' + weapon));
		push(0, (unsigned char)('0' + weapon));
		return;
	}
	if (axis == 0)                        /* main knob: turning */
		key = value > 0 ? DK_RIGHT : DK_LEFT;
	else                                  /* VOL: forward and back, up and down in the menus */
		key = value > 0 ? DK_UP : DK_DOWN;
	int n = value < 0 ? -value : value;
	if (p->key && p->key != key) {
		push(0, p->key);
		p->key = 0;
	}
	if (!p->key) {
		push(1, key);
		p->key = key;
		p->until = now_ms();
	}
	uint32_t t = now_ms();
	if (p->until < t)
		p->until = t;
	p->until += (uint32_t)(axis == 0 ? 45 : 90) * (uint32_t)n;
	if (p->until > t + 400)
		p->until = t + 400;
}

static void poll_input(void)
{
	struct input_event ev;
	while (poll(pfd, (nfds_t)n_in, 0) > 0) {
		bool any = false;
		for (int i = 0; i < n_in; i++) {
			if (!(pfd[i].revents & POLLIN))
				continue;
			if (read(in_fd[i], &ev, sizeof ev) != (ssize_t)sizeof ev)
				continue;
			any = true;
			if (ev.type == EV_KEY) {
				if (ev.code == KEY_POWER && ev.value == 1)
					leave(RB_POWER_OFF);
				unsigned char k = key_for(ev.code);
				if (k && (ev.value == 0 || ev.value == 1))
					push(ev.value, k);
			} else if (ev.type == EV_REL && ev.value) {
				if (ev.code == REL_X) knob(0, ev.value);
				else if (ev.code == REL_Y) knob(1, ev.value);
				else if (ev.code == REL_Z) knob(2, ev.value);
			}
		}
		if (!any)
			break;
	}
	uint32_t t = now_ms();
	for (int i = 0; i < 3; i++)
		if (pulses[i].key && (int32_t)(t - pulses[i].until) >= 0) {
			push(0, pulses[i].key);
			pulses[i].key = 0;
		}
}

static void open_inputs(void)
{
	DIR *d = opendir("/dev/input");
	struct dirent *e;
	if (!d)
		return;
	while ((e = readdir(d)) && n_in < MAX_DEVS) {
		char path[300];
		if (strncmp(e->d_name, "event", 5))
			continue;
		snprintf(path, sizeof path, "/dev/input/%s", e->d_name);
		int fd = open(path, O_RDONLY | O_NONBLOCK);
		if (fd < 0)
			continue;
		ioctl(fd, EVIOCGRAB, 1);
		pfd[n_in].fd = fd;
		pfd[n_in].events = POLLIN;
		in_fd[n_in++] = fd;
	}
	closedir(d);
}

int DG_GetKey(int *pressed, unsigned char *key)
{
	poll_input();
	if (q_r == q_w)
		return 0;
	unsigned short v = queue[q_r];
	q_r = (q_r + 1) % QSIZE;
	*pressed = v >> 8;
	*key = (unsigned char)(v & 0xff);
	return 1;
}

/* ------------------------------------------------------------------------------------------ */
/* The rest of the platform                                                                   */
/* ------------------------------------------------------------------------------------------ */
/* Test on a PC: DOOM_TEST_FB=480x800 draws into memory, DOOM_TEST_FRAMES=n writes frame n (the
 * raw framebuffer, 32-bit) to DOOM_TEST_OUT and stops */
static int test_frames, frame_no;

static bool test_fb(void)
{
	const char *t = getenv("DOOM_TEST_FB");
	if (!t || sscanf(t, "%ux%u", &fb_w, &fb_h) != 2)
		return false;
	fb_bpp = 4;
	fb_stride = fb_w * 4;
	vinfo.red.offset = 16;
	vinfo.green.offset = 8;
	vinfo.blue.offset = 0;
	vinfo.bits_per_pixel = 32;
	fb = calloc(fb_stride, fb_h);
	test_frames = getenv("DOOM_TEST_FRAMES") ? atoi(getenv("DOOM_TEST_FRAMES")) : 200;
	return true;
}

static void test_dump(void)
{
	if (!test_frames || ++frame_no < test_frames)
		return;
	const char *out = getenv("DOOM_TEST_OUT");
	FILE *f = fopen(out ? out : "frame.raw", "wb");
	if (f) {
		fwrite(fb, fb_stride, fb_h, f);
		fclose(f);
	}
	exit(0);
}

void DG_Init(void)
{
	struct fb_fix_screeninfo finfo;
	if (test_fb()) {
		if (fb_w > fb_h && rotate != 0)
			rotate = 0;
		setup_maps();
		return;
	}
	fb_fd = open("/dev/fb0", O_RDWR);
	if (fb_fd < 0) {
		say("Doom: no /dev/fb0 (%s)\n", strerror(errno));
		exit(1);
	}
	ioctl(fb_fd, FBIOGET_VSCREENINFO, &vinfo);
	fb_w = vinfo.xres;
	fb_h = vinfo.yres;
	fb_bpp = vinfo.bits_per_pixel / 8;
	fb_stride = ioctl(fb_fd, FBIOGET_FSCREENINFO, &finfo) == 0 ? finfo.line_length : fb_w * fb_bpp;
	if (fb_bpp != 4 && fb_bpp != 2) {
		say("Doom: %u bpp framebuffer not supported\n", vinfo.bits_per_pixel);
		exit(1);
	}
	if (fb_w > fb_h && rotate != 0)       /* a landscape framebuffer needs no turning */
		rotate = 0;
	fb = mmap(NULL, fb_stride * fb_h, PROT_READ | PROT_WRITE, MAP_SHARED, fb_fd, 0);
	if (fb == MAP_FAILED) {
		say("Doom: mmap /dev/fb0 failed (%s)\n", strerror(errno));
		exit(1);
	}
	tty_fd = open("/dev/tty0", O_RDWR);
	if (tty_fd >= 0)
		ioctl(tty_fd, KDSETMODE, KD_GRAPHICS);   /* no console text over the picture */
	ioctl(fb_fd, FBIOBLANK, FB_BLANK_UNBLANK);
	memset(fb, 0, fb_stride * fb_h);
	setup_maps();
	open_inputs();
}

void DG_SleepMs(uint32_t ms)
{
	usleep(ms * 1000);
}

uint32_t DG_GetTicksMs(void)
{
	return now_ms();
}

void DG_SetWindowTitle(const char *title)
{
	(void)title;
}

/* As init: the filesystems it needs, writable for the settings and saved games */
static void as_init(void)
{
	mkdir("/proc", 0755);
	mkdir("/sys", 0755);
	mkdir("/dev", 0755);
	mount("proc", "/proc", "proc", 0, NULL);
	mount("sysfs", "/sys", "sysfs", 0, NULL);
	mount("devtmpfs", "/dev", "devtmpfs", 0, NULL);   /* already there with DEVTMPFS_MOUNT */
	mount("", "/", "", MS_REMOUNT, NULL);               /* read-write */
	setenv("HOME", "/doom", 1);
	setenv("DOOMWADDIR", "/doom", 1);
	if (chdir("/doom") != 0)
		say("Doom: no /doom\n");
}

static const char *find_iwad(void)
{
	/* a full game copied there wins; Freedoom otherwise */
	static const char *names[] = {"/doom/doom2.wad", "/doom/doom.wad", "/doom/doom1.wad",
	                              "/doom/freedoom2.wad", "/doom/freedoom1.wad", NULL};
	for (int i = 0; names[i]; i++)
		if (access(names[i], R_OK) == 0)
			return names[i];
	return "/doom/freedoom1.wad";
}

int main(int argc, char **argv)
{
	clock_gettime(CLOCK_MONOTONIC, &t0);
	if (getpid() == 1)
		as_init();
	const char *r = getenv("DOOM_ROTATE");
	if (r)
		rotate = atoi(r);
	signal(SIGTERM, on_signal);
	signal(SIGINT, on_signal);
	atexit(at_exit);

	char *args[16];
	int n = 0;
	for (int i = 0; i < argc && n < 12; i++)
		args[n++] = argv[i];
	bool has_iwad = false;
	for (int i = 1; i < argc; i++)
		if (!strcmp(argv[i], "-iwad"))
			has_iwad = true;
	if (!has_iwad) {
		args[n++] = "-iwad";
		args[n++] = (char *)find_iwad();
	}
	args[n] = NULL;

	doomgeneric_Create(n, args);
	for (;;)
		doomgeneric_Tick();
	return 0;
}
