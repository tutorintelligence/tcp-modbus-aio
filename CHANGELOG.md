# CHANGELOG


## v0.4.4 (2025-08-18)

### Bug Fixes

- Bump semantic release
  ([`5724aee`](https://github.com/tutorintelligence/tcp-modbus-aio/commit/5724aeebdc2313e5578e5290c938b5584de5c114))

- Checkout v4
  ([`5ada130`](https://github.com/tutorintelligence/tcp-modbus-aio/commit/5ada130ac2c434648f7429991aa90d9193ebfcb0))

- Type error
  ([`1540a58`](https://github.com/tutorintelligence/tcp-modbus-aio/commit/1540a583c82b3b916fa7ef5531c5191159f3232c))


## v0.4.3 (2024-10-23)

### Bug Fixes

- Prevent multiple tasks from using the same connection
  ([#5](https://github.com/tutorintelligence/tcp-modbus-aio/pull/5),
  [`c40c161`](https://github.com/tutorintelligence/tcp-modbus-aio/commit/c40c161fe61dc13c47c1546c3df4213032c0d25c))

Co-authored-by: Alon Kosowsky-Sachs <alon@tutorintelligence.com>


## v0.4.2 (2024-10-10)

### Bug Fixes

- Retry on timeout ([#4](https://github.com/tutorintelligence/tcp-modbus-aio/pull/4),
  [`0ce5417`](https://github.com/tutorintelligence/tcp-modbus-aio/commit/0ce5417e3fe1dfaeff35a490ee16dd060417e61e))


## v0.4.1 (2024-07-17)

### Bug Fixes

- Retry in more circumstances ([#3](https://github.com/tutorintelligence/tcp-modbus-aio/pull/3),
  [`5256c58`](https://github.com/tutorintelligence/tcp-modbus-aio/commit/5256c58b19732c0b85f50ef12c07d52d6f8dc86a))


## v0.4.0 (2024-07-16)

### Features

- Add reconnect cooldown ([#2](https://github.com/tutorintelligence/tcp-modbus-aio/pull/2),
  [`706938d`](https://github.com/tutorintelligence/tcp-modbus-aio/commit/706938d7918a1a11f02250efa80ae2130fb4e3f5))


## v0.3.0 (2024-07-10)

### Features

- Support socks proxy
  ([`12d7d4a`](https://github.com/tutorintelligence/tcp-modbus-aio/commit/12d7d4a09041d059cc8124f2ae9ea3dae67aa46f))


## v0.2.13 (2024-07-05)

### Bug Fixes

- Better stream reconstruction logic to handle backpressure and connectionreseterrors
  ([`1830b13`](https://github.com/tutorintelligence/tcp-modbus-aio/commit/1830b13ca5ebe5dfdfde4a7d840730ea8ae6c166))


## v0.2.12 (2024-07-05)

### Bug Fixes

- Better handle ConnectionResetError and log timing
  ([`1c8fab8`](https://github.com/tutorintelligence/tcp-modbus-aio/commit/1c8fab8087aac3c10252a261c47199e7d6cc4e5f))


## v0.2.11 (2024-07-05)

### Bug Fixes

- Do not release connection lock unless you have it
  ([`53a64b3`](https://github.com/tutorintelligence/tcp-modbus-aio/commit/53a64b38a4accd917424181dc5a584b83f88100d))


## v0.2.10 (2024-07-05)

### Bug Fixes

- Refactor connection to better handle dropped data in stream
  ([`db08254`](https://github.com/tutorintelligence/tcp-modbus-aio/commit/db0825429192317678aa72b02f41262bb87e0600))


## v0.2.9 (2024-07-04)

### Bug Fixes

- More correct accounting for timeouts
  ([`12c9f62`](https://github.com/tutorintelligence/tcp-modbus-aio/commit/12c9f62efc9c07daf4fe21a5515e0c69cb7e6cc7))


## v0.2.8 (2024-06-27)

### Bug Fixes

- Catch OSError on clearing tcp connection
  ([`0e55b6e`](https://github.com/tutorintelligence/tcp-modbus-aio/commit/0e55b6eea275f77c31fc784a785dca48241d6a03))


## v0.2.7 (2024-05-02)

### Bug Fixes

- Self-correct transaction id mismatch errors
  ([`3335a79`](https://github.com/tutorintelligence/tcp-modbus-aio/commit/3335a79933579e600b0ae56ecd94ac5998295ead))


## v0.2.6 (2024-05-01)

### Bug Fixes

- Connectionreseterror
  ([`c7d54c2`](https://github.com/tutorintelligence/tcp-modbus-aio/commit/c7d54c2590f363527ac2d5e969be4c5bec68841f))


## v0.2.5 (2024-05-01)

### Bug Fixes

- Fix TYPE_CHECKING 3
  ([`de28e2a`](https://github.com/tutorintelligence/tcp-modbus-aio/commit/de28e2a7c88bff9498a16ef77e2796f72a24b57a))


## v0.2.4 (2024-05-01)

### Bug Fixes

- More type checking client.py
  ([`211ee97`](https://github.com/tutorintelligence/tcp-modbus-aio/commit/211ee979fa235215818ed68418e8879a7398551a))


## v0.2.3 (2024-05-01)

### Bug Fixes

- Handle TYPE_CHECKING correctly
  ([`f1dcac6`](https://github.com/tutorintelligence/tcp-modbus-aio/commit/f1dcac6ab52b25441f651becf8e20006fe6ffd20))


## v0.2.2 (2024-05-01)

### Bug Fixes

- Handle timeout on connection close
  ([#1](https://github.com/tutorintelligence/tcp-modbus-aio/pull/1),
  [`6062ff8`](https://github.com/tutorintelligence/tcp-modbus-aio/commit/6062ff84dd4c6ce69d91603f2869ec86560d49ee))


## v0.2.1 (2024-04-25)

### Bug Fixes

- Ping stderr to devnull
  ([`c38a840`](https://github.com/tutorintelligence/tcp-modbus-aio/commit/c38a840539db714ac27e293eacf153d573e4bf2f))


## v0.2.0 (2024-04-21)

### Features

- Is_pingable check method and error on closed client
  ([`30aa42e`](https://github.com/tutorintelligence/tcp-modbus-aio/commit/30aa42e47ef7d2e0b1f3cea0a77dc464d389e0f3))


## v0.1.1 (2024-04-16)

### Bug Fixes

- Extract constants from classvars to be globals
  ([`c3c39da`](https://github.com/tutorintelligence/tcp-modbus-aio/commit/c3c39da0eedf1d84fbc8cad9d71147c01fd094c9))


## v0.1.0 (2024-04-16)

### Features

- Initial open source release
  ([`0455c21`](https://github.com/tutorintelligence/tcp-modbus-aio/commit/0455c2111e76a60503f5ea140d2d5ed1d684bc80))
