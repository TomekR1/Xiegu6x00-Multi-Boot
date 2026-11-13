/* What Chocolate Doom's i_oplmusic.c expects of i_sound.h and doomgeneric's lacks (Xiegu Multi Patcher) */
#ifndef X6100_OPL_COMPAT_H
#define X6100_OPL_COMPAT_H
typedef enum
{
    opl_doom1_1_666,    // Doom 1 v1.666
    opl_doom2_1_666,    // Doom 2 v1.666, Hexen, Heretic
    opl_doom_1_9        // Doom v1.9, Strife
} opl_driver_ver_t;

void I_SetOPLDriverVer(opl_driver_ver_t ver);

#include <stddef.h>
void *I_Realloc(void *ptr, size_t size);   /* Chocolate Doom's i_system.h; x6100_sound.c has it */

/* Chocolate Doom 3's doomtype.h has it, doomgeneric's not */
#include "doomtype.h"
#ifndef PACKED_STRUCT
#define PACKED_STRUCT(...) struct __VA_ARGS__ PACKEDATTR
#endif
#endif
