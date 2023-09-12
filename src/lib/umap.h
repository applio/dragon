#ifndef HAVE_DRAGON_MAP_H
#define HAVE_DRAGON_MAP_H

#include <stdint.h>
#include <dragon/return_codes.h>
#include "shared_lock.h"

#ifdef __cplusplus
extern "C" {
#endif

typedef struct dragonMap_st {
    dragonLock_t _dlock;
    void * _lmem;
    void * _map;
} dragonMap_t;

dragonError_t
dragon_umap_create(dragonMap_t * dmap, uint64_t seed);

dragonError_t
dragon_umap_destroy(dragonMap_t * dmap);

dragonError_t
dragon_umap_additem(dragonMap_t * dmap, const uint64_t key, const void * data);

dragonError_t
dragon_umap_additem_genkey(dragonMap_t * dmap, const void * data, uint64_t * new_key);

dragonError_t
dragon_umap_getitem(dragonMap_t * dmap, const uint64_t key, void ** data);

dragonError_t
dragon_umap_delitem(dragonMap_t * dmap, const uint64_t key);


#ifdef __cplusplus
}
#endif

#endif
