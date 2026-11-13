// SPDX-License-Identifier: GPL-2.0-or-later
/*
 * Doom's sound effects on the Xiegu X6100: the DMX sound lumps mixed in a thread of their own and
 * played through the SoC's codec with tinyalsa (BSD-3-Clause), the codec's mixer set as
 * OpenX6X00 sets it (its /var/lib/alsa/asound.state: AIF1 DA0 -> DAC -> Headphone, which goes on
 * to the radio board). The music: Chocolate Doom's OPL player and the Nuked OPL3 emulator
 * (opl_x6100.c), rendered in the same thread and mixed in.
 *
 * /boot/doom.txt (the card's BOOT partition, read by doomgeneric_x6100.c) may hold
 *   volume=N   the effects' loudness, 0..200 (%; 100 by default)
 *   music=N    the music's, the same way
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

/* What Chocolate Doom's MIDI reader expects of i_system.c */
void I_Error(char *error, ...);
void *I_Realloc(void *ptr, size_t size)
{
	void *p = realloc(ptr, size);
	if (p == NULL && size != 0)
		I_Error("I_Realloc: failed on reallocation of %zu bytes", size);
	return p;
}

int x6100_sound_volume = 100;   /* set from /boot/doom.txt before the sound starts */
int x6100_music_volume = 100;   /* the same, for the music */
unsigned int x6100_sound_rate;  /* the output rate once the sound runs (the OPL emulator's too) */
unsigned int x6100_opl_rate;    /* 0: the OPL emulator at the output rate (as on the card that played) */
int x6100_headphone = 47;       /* headphone= in doom.txt */
int x6100_rx_mute = 1;          /* rxmute= in doom.txt: the receiver's RF gain 0 (its hiss) */
int x6100_record = 1;           /* record= in doom.txt: the base board's play mode */
int opl_x6100_render(int16_t *buffer, unsigned int frames);

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
static FILE *test_out;          /* DOOM_TEST_PCM=file: the PC test writes the sound there */

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
	{"Headphone Playback Volume", NULL, 47},       /* headphone= in doom.txt */
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
		int value = settings[i].value;
		if (!strcmp(settings[i].name, "Headphone Playback Volume"))
			value = x6100_headphone < 0 ? 0 : x6100_headphone > 63 ? 63 : x6100_headphone;
		if (settings[i].text) {
			mixer_ctl_set_enum_by_string(c, settings[i].text);
		} else {
			for (unsigned v = 0; v < mixer_ctl_get_num_values(c); v++)
				mixer_ctl_set_value(c, v, value);
		}
	}
	mixer_close(m);
}

/* The radio's base board, over I2C as its own software does it (bus 0, address 0x72, 32-bit
 * registers, X6100Control's numbering): a register's address big-endian, its value little-endian */
static bool base_write(int fd, unsigned reg, uint32_t val)
{
	uint16_t addr = (uint16_t)(reg * 4);
	uint8_t buf[6] = {(uint8_t)(addr >> 8), (uint8_t)addr, (uint8_t)val, (uint8_t)(val >> 8),
	                  (uint8_t)(val >> 16), (uint8_t)(val >> 24)};
	struct i2c_msg msg = {.addr = 0x72, .flags = 0, .len = sizeof buf, .buf = buf};
	struct i2c_rdwr_ioctl_data d = {.msgs = &msg, .nmsgs = 1};
	if (ioctl(fd, I2C_RDWR, &d) < 0) {
		fprintf(stderr, "sound: base board register %u: %s\n", reg, strerror(errno));
		return false;
	}
	return true;
}

/* The radio's speaker playing the SoC's sound, as OpenX6X00 sets it to play audio (its
 * AUDIO_PLAY_ON): the record bit (voice_rec, 0x8) of register 12 on, so the codec's output goes
 * to the speaker; both microphones' gain 0 in register 20 (line in/out at its default 10), so no
 * microphone is heard; the AF volume, register 14, at vol (0..55). Without the radio's own
 * software none of it is set, and the codec's sound only went towards the transmitter. */
void x6100_radio_audio(int vol)
{
	if (vol < 0 || vol > 55)
		vol = 20;
	int fd = open("/dev/i2c-0", O_RDWR);
	if (fd < 0) {
		fprintf(stderr, "sound: /dev/i2c-0: %s\n", strerror(errno));
		return;
	}
	bool ok = base_write(fd, 20, 10u | (10u << 8)) &&     /* line in 10, line out 10, mics 0 */
	          base_write(fd, 12, x6100_record ? 0x8 : 0) && /* record: the codec to the speaker */
	          base_write(fd, 14, (uint32_t)vol);            /* AF volume */
	if (ok && x6100_rx_mute)
		ok = base_write(fd, 15, 10u << 8);              /* RF gain 0: no receiver hiss; TX 1 W kept */
	fprintf(stderr, "sound: radio speaker %s (record on, mics off, AF volume %d)\n",
	        ok ? "set" : "NOT set", vol);
	close(fd);
}

/* ------------------------------------------------------------------------------------------ */
/* Mixing                                                                                     */
/* ------------------------------------------------------------------------------------------ */
unsigned int x6100_xruns;        /* the sound's gaps (the card's buffer ran dry), for the log */

/* Up to 20000 as it is, above that bent smoothly towards 32767: loud moments get rounder, not cut */
static int16_t soft_limit(int32_t v)
{
	const int32_t knee = 20000, room = 32767 - 20000;
	int32_t a = v < 0 ? -v : v;
	if (a > knee) {
		int64_t over = a - knee;
		a = knee + (int32_t)(over * room / (over + room));
	}
	return (int16_t)(v < 0 ? -a : a);
}

static void *mix_thread(void *arg)
{
	(void)arg;
	static int16_t out[PERIOD * 2], music[PERIOD * 2];
	while (running) {
		int32_t acc[PERIOD * 2];
		memset(acc, 0, sizeof acc);
		if (opl_x6100_render(music, PERIOD))  /* the OPL emulator is quiet: x3 at 100 % */
			for (int i = 0; i < PERIOD * 2; i++)
				acc[i] = music[i] * 3 * x6100_music_volume / 100;
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
				/* linear between two samples: Doom's 11 kHz effects at 48 kHz without the grit */
				int a = (int)ch->data[idx] - 128;
				int b = idx + 1 < ch->len ? (int)ch->data[idx + 1] - 128 : a;
				int s = (a << 8) + (((b - a) * (int)(ch->pos & 0xFFFF)) >> 8);
				acc[2 * i] += s * ch->lv / 255;
				acc[2 * i + 1] += s * ch->rv / 255;
				ch->pos += ch->step;
			}
		}
		pthread_mutex_unlock(&lock);
		/* One speaker: both channels the same (the codec mixes them to mono and two loud channels
		 * overflowed there), and a soft limiter instead of cutting the peaks flat (that crackled) */
		for (int i = 0; i < PERIOD; i++) {
			int32_t v = (acc[2 * i] + acc[2 * i + 1]) / 2 * x6100_sound_volume / 100;
			out[2 * i] = out[2 * i + 1] = soft_limit(v);
		}
		if (test_out) {                       /* the PC test: into a file, in real time */
			fwrite(out, sizeof out, 1, test_out);
			fflush(test_out);
			usleep(PERIOD * 1000000u / rate);
		} else if (pcm_writei(pcm, out, PERIOD) < 0) {
			x6100_xruns++;
			pcm_prepare(pcm);                 /* an underrun: on again */
		}
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
	const char *test = getenv("DOOM_TEST_PCM");
	if (test && (test_out = fopen(test, "wb"))) {
		rate = x6100_sound_rate = 48000;
		running = true;
		return pthread_create(&thread, NULL, mix_thread, NULL) == 0;
	}
	set_mixer();
	{
		FILE *c = fopen("/proc/asound/cards", "r");
		char line[160];
		fprintf(stderr, "sound: cards:\n");
		while (c && fgets(line, sizeof line, c))
			fprintf(stderr, "  %s", line);
		if (c)
			fclose(c);
		else
			fprintf(stderr, "  /proc/asound/cards: none\n");
	}
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
	if (!pcm) {
		fprintf(stderr, "sound: no PCM output opened\n");
		return false;
	}
	fprintf(stderr, "sound: playing at %u Hz\n", rate);
	x6100_sound_rate = rate;
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
