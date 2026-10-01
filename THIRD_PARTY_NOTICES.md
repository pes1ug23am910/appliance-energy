# Third-party notices

Original Appliance Energy source code is Copyright (c) 2026 Yash Verma and is
provided under the [MIT License](LICENSE). Third-party material retains the
licenses and attribution described below; the project license does not replace
them. Dependencies downloaded during installation or a build retain their own
licenses.

## ESP-MQTT patch

[`firmware/esp8266/patches/mqtt-retain.patch`](firmware/esp8266/patches/mqtt-retain.patch)
contains context from and changes to `mqtt_client.c` and `include/mqtt_client.h`
from [Espressif ESP-MQTT, commit
`01594bf118ae502b5a0ead040446f2be75d26223`](https://github.com/espressif/esp-mqtt/tree/01594bf118ae502b5a0ead040446f2be75d26223).
The ESP8266 Docker build checks that exact revision before applying the patch.

The upstream material is licensed under the Apache License, Version 2.0.
[The bundled license copy](LICENSES/Apache-2.0.txt) is reproduced unchanged from
[that revision's license](https://github.com/espressif/esp-mqtt/blob/01594bf118ae502b5a0ead040446f2be75d26223/LICENSE),
including its **Copyright 2016 Tuan PM** notice. The upstream header also credits
`Tuan PM <tuanpm at live dot com>`.

Local changes expose the original MQTT PUBLISH RETAIN bit in delivered events,
preserve it across continuation reads, and check signed transport-read failures
before conversion to an unsigned length. These changes are identified by the
patch; the upstream implementation is not original Appliance Energy code.

## REFIT dataset

REFIT observations are not distributed in this repository. The optional data
adapter downloads a bounded sample from the [cleaned REFIT record](https://zenodo.org/records/5063428)
and writes source URLs and a content hash into its local provenance record.
The [University of Strathclyde dataset record](https://pureportal.strath.ac.uk/en/datasets/refit-electrical-load-measurements/)
identifies the raw dataset as **CC BY 4.0** and requests citation of:

Murray, D.; Stankovic, L.; Stankovic, V. *An electrical load measurements dataset
of United Kingdom households from a two-year longitudinal study*. Scientific
Data 4, 160122 (2017). [doi:10.1038/sdata.2016.122](https://doi.org/10.1038/sdata.2016.122).

The adapter marks the public-data cohort and labels its energy counter as
estimated from power. Downloaded observations retain their source attribution
and terms; the MIT license does not apply to them.
