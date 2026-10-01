#ifndef APPLIANCE_DESIRED_STATE_H
#define APPLIANCE_DESIRED_STATE_H
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#define DESIRED_RECORD_SIZE 64
#define DESIRED_MAX_REVISION UINT64_C(9007199254740991)
typedef struct {
    uint64_t revision;
    int64_t expires_epoch;
    bool power;
    uint8_t speed;
    char command_id[37];
} desired_value_t;
typedef struct {
    desired_value_t value;
    bool faulted;
    void *context;
    int (*write)(void *, const uint8_t *, size_t);
} desired_store_t;
typedef enum { DESIRED_ACCEPTED, DESIRED_REJECTED, DESIRED_IO } desired_result_t;
/* read: 0 success, 1 absent, -1 uncertain I/O. write includes durable commit. */
bool desired_open(desired_store_t *, void *, int (*read)(void *,uint8_t *,size_t *), int (*write)(void *,const uint8_t *,size_t));
desired_result_t desired_accept(desired_store_t *, const desired_value_t *, int64_t now);
bool desired_restorable(const desired_store_t *, int64_t now);
bool desired_uuid_valid(const char *);
#endif
