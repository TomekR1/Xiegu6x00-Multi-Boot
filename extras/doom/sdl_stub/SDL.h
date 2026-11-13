/* The few SDL calls the OPL and MIDI code of Chocolate Doom makes, on pthreads (Xiegu Multi Patcher) */
#ifndef X6100_SDL_STUB_H
#define X6100_SDL_STUB_H
#include <pthread.h>
#include <stdint.h>
#include <stdlib.h>

typedef uint8_t Uint8;
typedef uint16_t Uint16;
typedef uint32_t Uint32;
typedef pthread_mutex_t SDL_mutex;
typedef pthread_cond_t SDL_cond;

static inline SDL_mutex *SDL_CreateMutex(void)
{
    SDL_mutex *m = malloc(sizeof *m);
    pthread_mutexattr_t a;
    pthread_mutexattr_init(&a);
    pthread_mutexattr_settype(&a, PTHREAD_MUTEX_RECURSIVE);
    pthread_mutex_init(m, &a);
    return m;
}
static inline int SDL_LockMutex(SDL_mutex *m) { return pthread_mutex_lock(m); }
static inline int SDL_UnlockMutex(SDL_mutex *m) { return pthread_mutex_unlock(m); }
static inline void SDL_DestroyMutex(SDL_mutex *m) { pthread_mutex_destroy(m); free(m); }
static inline SDL_cond *SDL_CreateCond(void)
{
    SDL_cond *c = malloc(sizeof *c);
    pthread_cond_init(c, NULL);
    return c;
}
static inline int SDL_CondSignal(SDL_cond *c) { return pthread_cond_signal(c); }
static inline int SDL_CondWait(SDL_cond *c, SDL_mutex *m) { return pthread_cond_wait(c, m); }
static inline void SDL_DestroyCond(SDL_cond *c) { pthread_cond_destroy(c); free(c); }
#define SDL_SwapBE16(x) ((uint16_t) __builtin_bswap16((uint16_t)(x)))
#define SDL_SwapBE32(x) ((uint32_t) __builtin_bswap32((uint32_t)(x)))
#endif
