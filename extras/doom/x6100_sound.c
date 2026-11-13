// SPDX-License-Identifier: GPL-2.0-or-later
/*
 * Doom's sound effects on the Xiegu X6100: the DMX sound lumps mixed in a thread of their own and
 * played through the SoC's codec with tinyalsa (BSD-3-Clause), the codec's mixer set as
 * OpenX6X00 sets it (its /var/lib/alsa/asound.state: AIF1 DA0 -> DAC -> Headphone, which goes on
 * to the radio board). No music: Doom's needs an OPL synthesiser.
 *
 * /boot/doom.txt (the card's BOOT partition, read by doomgeneric_x6100.c) may hold
 *   volume=N   the effects' loudness, 0..200 (%; 100 by default)
 *   rxvol=N    the radio board's AF volume, 0..55, set over I2C as the radio's own software does
 *              (bus 0, address 0x72, register x6100_rxvol); left alone when not given
 */
#include <errno.h>
#include <fcntl.h>
#include <linux/i2c-dev.h>
#include <linux/i2c.h>
#include <pthread.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <unistd.h>

#include <tinyalsa/asoundlib.h>

#include "deh_str.h"
#include "doomtype.h"
#include "i_sound.h"
#include "m_misc.h"
#include "w_wad.h"
#include "z_zone.h"

/* What i_sound.c expects of a sound back end */
int use_libsamplerate = 0;
float libsamplerate_scale = 0.65f;
void I_InitTimidityConfig(void) {}

int x6100_sound_volume = 100;   /* set from /boot/doom.txt before the sound starts */

#define CHANNELS 16
#define PERIOD   512

struct chan {
	const uint8_t *data;   /* unsigned 8-bit samples */
	uint32_t len;
	uint32_t pos;          /* 16.16 */
	uint32_t step;         /* 16.16 */
	int lv, rv;            /* 0..255 */
	bool on;
};

static struct chan chans[CHANNELS];
static pthread_mutex_t lock = PTHREAD_MUTEX_INITIALIZER;
static pthread_t thread;
static volatile bool running;
static struct pcm *pcm;
static unsigned rate;
static boolean sfx_prefix;

/* ------------------------------------------------------------------------------------------ */
/* The codec's mixer, as OpenX6X00 leaves it                                                   */
/* ------------------------------------------------------------------------------------------ */
struct setting {
	const char *name;
	const char *text;      /* an enumerated control's item, or NULL */
	int value;
};

static const struct setting settings[] = {
	{"AIF1 DA0 Playback Volume", NULL, 161},
	{"AIF1 Slot 0 Digital DAC Playback Switch", NULL, 1},
	{"AIF1 DA0 Stereo Playback Route", "Mix Mono", 0},
	{"Headphone Source Playback Route", "DAC", 0},
	{"Headphone Playback Switch", NULL, 1},
	{"Headphone Playback Volume", NULL, 47},
};

static void set_mixer(void)
{
	struct mixer *m = mixer_open(0);
	if (!m) {
		fprintf(stderr, "sound: no mixer\n");
		return;
	}
	for (size_t i = 0; i < sizeof settings / sizeof settings[0]; i++) {
		struct mixer_ctl *c = mixer_get_ctl_by_name(m, settings[i].name);
		if (!c) {
			fprintf(stderr, "sound: no control '%s'\n", settings[i].name);
			continue;
		}
		if (settings[i].text) {
			mixer_ctl_set_enum_by_string(c, settings[i].text);
		} else {
			for (unsigned v = 0; v < mixer_ctl_get_num_values(c); v++)
				mixer_ctl_set_value(c, v, settings[i].value);
		}
	}
	mixer_close(m);
}

/* The radio board's AF volume (what the VOL knob sets in the radio's software) */
void x6100_set_rxvol(int vol)
{
	if (vol < 0 || vol > 55)
		return;
	int fd = open("/dev/i2c-0", O_RDWR);
	if (fd < 0)
		return;
	uint16_t addr = 14 * 4;                   /* x6100_rxvol, 32-bit registers */
	uint8_t buf[6] = {(uint8_t)(addr >> 8), (uint8_t)addr, (uint8_t)vol, 0, 0, 0};
	struct i2c_msg msg = {.addr = 0x72, .flags = 0, .len = sizeof buf, .buf = buf};
	struct i2c_rdwr_ioctl_data d = {.msgs = &msg, .nmsgs = 1};
	if (ioctl(fd, I2C_RDWR, &d) < 0)
		fprintf(stderr, "sound: rxvol: %s\n", strerror(errno));
	close(fd);
}

/* ------------------------------------------------------------------------------------------ */
/* Mixing                                                                                     */
/* ------------------------------------------------------------------------------------------ */
static void *mix_thread(void *arg)
{
	(void)arg;
	static int16_t out[PERIOD * 2];
	while (running) {
		int32_t acc[PERIOD * 2];
		memset(acc, 0, sizeof acc);
		pthread_mutex_lock(&lock);
		for (int c = 0; c < CHANNELS; c++) {
			struct chan *ch = &chans[c];
			if (!ch->on)
				continue;
			for (int i = 0; i < PERIOD; i++) {
				uint32_t idx = ch->pos >> 16;
				if (idx >= ch->len) {
					ch->on = false;
					break;
				}
				int s = ((int)ch->data[idx] - 128) << 8;
				acc[2 * i] += s * ch->lv / 255;
				acc[2 * i + 1] += s * ch->rv / 255;
				ch->pos += ch->step;
			}
		}
		pthread_mutex_unlock(&lock);
		for (int i = 0; i < PERIOD * 2; i++) {
			int32_t v = acc[i] * x6100_sound_volume / 100;
			out[i] = (int16_t)(v > 32767 ? 32767 : v < -32768 ? -32768 : v);
		}
		if (pcm_writei(pcm, out, PERIOD) < 0)
			pcm_prepare(pcm);                 /* an underrun: on again */
	}
	return NULL;
}

/* ------------------------------------------------------------------------------------------ */
/* Doom's sound module                                                                        */
/* ------------------------------------------------------------------------------------------ */
static boolean snd_init(boolean use_sfx_prefix)
{
	static const unsigned rates[] = {48000, 44100, 32000, 22050, 16000};
	sfx_prefix = use_sfx_prefix;
	set_mixer();
	for (size_t i = 0; i < sizeof rates / sizeof rates[0] && !pcm; i++) {
		struct pcm_config cfg = {
			.channels = 2, .rate = rates[i], .period_size = PERIOD, .period_count = 4,
			.format = PCM_FORMAT_S16_LE, .start_threshold = PERIOD,
		};
		struct pcm *p = pcm_open(0, 0, PCM_OUT, &cfg);
		if (p && pcm_is_ready(p)) {
			pcm = p;
			rate = rates[i];
		} else if (p) {
			fprintf(stderr, "sound: %u Hz: %s\n", rates[i], pcm_get_error(p));
			pcm_close(p);
		}
	}
	if (!pcm)
		return false;
	running = true;
	if (pthread_create(&thread, NULL, mix_thread, NULL)) {
		running = false;
		return false;
	}
	return true;
}

static void snd_shutdown(void)
{
	if (running) {
		running = false;
		pthread_join(thread, NULL);
	}
	if (pcm) {
		pcm_close(pcm);
		pcm = NULL;
	}
}

static int snd_lump(sfxinfo_t *sfx)
{
	char name[9];
	if (sfx->link)
		sfx = sfx->link;
	if (sfx_prefix)
		M_snprintf(name, sizeof name, "ds%s", DEH_String(sfx->name));
	else
		M_StringCopy(name, DEH_String(sfx->name), sizeof name);
	return W_GetNumForName(name);
}

static void levels(int vol, int sep, int *lv, int *rv)
{
	if (vol < 0) vol = 0;
	if (vol > 127) vol = 127;
	if (sep < 0) sep = 0;
	if (sep > 254) sep = 254;
	*lv = vol * (254 - sep) / 127;            /* 0..254: louder on the side it comes from */
	*rv = vol * sep / 127;
}

static int snd_start(sfxinfo_t *sfx, int channel, int vol, int sep)
{
	if (channel < 0 || channel >= CHANNELS)
		return -1;
	if (sfx->lumpnum < 0)
		sfx->lumpnum = snd_lump(sfx);
	const uint8_t *d = W_CacheLumpNum(sfx->lumpnum, PU_STATIC);
	int size = W_LumpLength(sfx->lumpnum);
	if (size < 8 || d[0] != 3 || d[1] != 0)
		return -1;
	unsigned srate = d[2] | (d[3] << 8);
	uint32_t len = d[4] | (d[5] << 8) | (d[6] << 16) | ((uint32_t)d[7] << 24);
	if (len > (uint32_t)size - 8)
		len = (uint32_t)size - 8;
	const uint8_t *s = d + 8;
	if (len > 32) {                            /* DMX pads 16 samples on both sides */
		s += 16;
		len -= 32;
	}
	pthread_mutex_lock(&lock);
	struct chan *ch = &chans[channel];
	ch->data = s;
	ch->len = len;
	ch->pos = 0;
	ch->step = (uint32_t)(((uint64_t)srate << 16) / (rate ? rate : 48000));
	levels(vol, sep, &ch->lv, &ch->rv);
	ch->on = true;
	pthread_mutex_unlock(&lock);
	return channel;
}

static void snd_stop(int channel)
{
	if (channel < 0 || channel >= CHANNELS)
		return;
	pthread_mutex_lock(&lock);
	chans[channel].on = false;
	pthread_mutex_unlock(&lock);
}

static boolean snd_playing(int channel)
{
	return channel >= 0 && channel < CHANNELS && chans[channel].on;
}

static void snd_params(int channel, int vol, int sep)
{
	if (channel < 0 || channel >= CHANNELS)
		return;
	pthread_mutex_lock(&lock);
	levels(vol, sep, &chans[channel].lv, &chans[channel].rv);
	pthread_mutex_unlock(&lock);
}

static void snd_update(void) {}
static void snd_cache(sfxinfo_t *sounds, int n) { (void)sounds; (void)n; }

static snddevice_t devices[] = {SNDDEVICE_SB, SNDDEVICE_PAS, SNDDEVICE_GUS, SNDDEVICE_WAVEBLASTER,
                                SNDDEVICE_SOUNDCANVAS, SNDDEVICE_AWE32};

sound_module_t DG_sound_module = {
	devices, sizeof devices / sizeof devices[0],
	snd_init, snd_shutdown, snd_lump, snd_update, snd_params, snd_start, snd_stop, snd_playing,
	snd_cache,
};

/* No music */
static boolean mus_init(void) { return false; }
static void mus_none(void) {}
static void mus_vol(int v) { (void)v; }
static void *mus_reg(void *d, int l) { (void)d; (void)l; return NULL; }
static void mus_unreg(void *h) { (void)h; }
static void mus_play(void *h, boolean l) { (void)h; (void)l; }
static boolean mus_playing(void) { return false; }

music_module_t DG_music_module = {
	NULL, 0, mus_init, mus_none, mus_vol, mus_none, mus_none, mus_reg, mus_unreg, mus_play,
	mus_none, mus_playing, mus_none,
};
