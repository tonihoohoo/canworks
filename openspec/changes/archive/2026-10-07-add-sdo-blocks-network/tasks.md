## 1. Plugin

- [x] 1.1 `PlcRequests::open(networks)` takes the number of networks; a request for a network the config does not have ends with ERROR_ID 6
- [x] 1.2 `take` and `cancel_taken` work per network; every network services program requests
- [x] 1.3 Unit test: requests per network, cancel per network, out-of-range network

## 2. Library

- [x] 2.1 `NETWORK : USINT` input on all eight blocks (library/generate.py), request carries it
- [x] 2.2 Rebuild openplc_canopen.stlib
- [x] 2.3 Simulation test: reads on two networks with the real blocks, a missing network, a lost node on one network

## 3. Configurator and docs

- [x] 3.1 Copy as ST call sets `NETWORK` and the network name with several networks; page test
- [x] 3.2 docs/plc-sdo.md, docs/config.md, docs/configurator.md and README.md describe the input
