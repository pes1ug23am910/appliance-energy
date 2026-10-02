#ifndef APPLIANCE_TLS_REQUIREMENTS_H
#define APPLIANCE_TLS_REQUIREMENTS_H

#include "sdkconfig.h"

/* A plausible application clock does not enable mbedTLS date checks. */
#if !defined(CONFIG_MBEDTLS_HAVE_TIME) || !CONFIG_MBEDTLS_HAVE_TIME
#error "TLS requires CONFIG_MBEDTLS_HAVE_TIME=y"
#endif
#if !defined(CONFIG_MBEDTLS_HAVE_TIME_DATE) || !CONFIG_MBEDTLS_HAVE_TIME_DATE
#error "TLS requires CONFIG_MBEDTLS_HAVE_TIME_DATE=y; enable certificate validity-date checks"
#endif

#endif
