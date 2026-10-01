#ifndef TELEMETRY_SPOOL_H
#define TELEMETRY_SPOOL_H
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define SPOOL_CAPACITY 64
#define SPOOL_PAYLOAD_MAX 768
#define SPOOL_RECORD_MAX (49 + SPOOL_PAYLOAD_MAX)
/* Storage returns 0 for success, 1 for absent, -1 for error. Writes and erases
 * include the durable commit. An error is ambiguous and requires reopening. */
typedef struct {
    void *context;
    int (*read)(void *, unsigned, uint8_t *, size_t *);
    int (*write)(void *, unsigned, const uint8_t *, size_t);
    int (*erase)(void *, unsigned);
} spool_storage_t;
typedef struct {
    spool_storage_t storage;
    char ids[SPOOL_CAPACITY][37];
    bool faulted;
} telemetry_spool_t;
typedef enum { SPOOL_OK, SPOOL_ABSENT, SPOOL_FULL, SPOOL_INVALID, SPOOL_IO } spool_result_t;
spool_result_t spool_open(telemetry_spool_t *spool, spool_storage_t storage);
spool_result_t spool_append(telemetry_spool_t *spool, const char *id, const char *payload);
spool_result_t spool_read(telemetry_spool_t *spool, unsigned slot, char *payload, size_t capacity);
/* Call only after a trusted application receipt with status == accepted. */
spool_result_t spool_accept(telemetry_spool_t *spool, const char *id);
unsigned spool_count(const telemetry_spool_t *spool);
#endif
