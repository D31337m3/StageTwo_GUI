# SPDX-FileCopyrightText: 2015-2016 Ideetron B.V.
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
`adafruit_tinylora`
====================================================
CircuitPython LoRaWAN implementation for use with
The Things Network.

* Author(s): adafruit

Implementation Notes
--------------------

**Hardware:**

* `Adafruit RFM95W LoRa Radio Transceiver Breakout <https://www.adafruit.com/product/3072>`_

**Software and Dependencies:**

* Adafruit CircuitPython firmware for the supported boards:
  https://github.com/adafruit/circuitpython/releases

* Adafruit's Bus Device library: https://github.com/adafruit/Adafruit_CircuitPython_BusDevice
"""

import time
from random import randint

import adafruit_bus_device.spi_device
from micropython import const

from adafruit_tinylora.adafruit_tinylora_encryption import AES

try:  # typing
    from types import TracebackType
    from typing import Optional, Type, Union

    import busio
    import digitalio
    from typing_extensions import (
        Annotated,
        Self,  # Python <3.11
        TypeAlias,
    )

    # type aliases
    bytearray2: TypeAlias = Annotated[bytearray, 2]
    bytearray4: TypeAlias = Annotated[bytearray, 4]
    bytearray16: TypeAlias = Annotated[bytearray, 16]

    registeraddress: TypeAlias = Union[const, int]
except ImportError:
    pass


__version__ = "2.2.21"
__repo__ = "https://github.com/adafruit/Adafruit_CircuitPython_TinyLoRa.git"

# RFM Module Settings
_MODE_SLEEP = const(0x00)
_MODE_LORA = const(0x80)
_MODE_STDBY = const(0x01)
_MODE_TX = const(0x83)
_TRANSMIT_DIRECTION_UP = const(0x00)
# RFM Registers
_REG_PA_CONFIG = const(0x09)
_REG_PREAMBLE_MSB = const(0x20)
_REG_PREAMBLE_LSB = const(0x21)
_REG_FRF_MSB = const(0x06)
_REG_FRF_MID = const(0x07)
_REG_FRF_LSB = const(0x08)
_REG_FEI_LSB = const(0x1E)
_REG_FEI_MSB = const(0x1D)
_REG_MODEM_CONFIG = const(0x26)
_REG_PAYLOAD_LENGTH = const(0x22)
_REG_FIFO_POINTER = const(0x0D)
_REG_FIFO_BASE_ADDR = const(0x80)
_REG_OPERATING_MODE = const(0x01)
_REG_VERSION = const(0x42)
_REG_PREAMBLE_DETECT = const(0x1F)
_REG_TIMER1_COEF = const(0x39)
_REG_NODE_ADDR = const(0x33)
_REG_IMAGE_CAL = const(0x3B)
_REG_RSSI_CONFIG = const(0x0E)
_REG_RSSI_COLLISION = const(0x0F)
_REG_DIO_MAPPING_1 = const(0x40)

# Freq synth step
_FSTEP = 32000000.0 / 524288


class TTN:
    """TTN Class"""

    def __init__(
        self,
        dev_address: bytearray4,
        net_key: bytearray16,
        app_key: bytearray16,
        country: str = "US",
    ):
        """Interface for TheThingsNetwork
        :param bytearray dev_address: TTN Device Address.
        :param bytearray net_key: TTN Network Key.
        :param bytearray app_key: TTN Application Key.
        :param string country: TTN Region.
        """
        self.dev_addr = dev_address
        self.net_key = net_key
        self.app_key = app_key
        self.region = country

    @property
    def country(self) -> str:
        """Returns the TTN Frequency Country."""
        return self.region

    @property
    def device_address(self) -> bytearray4:
        """Returns the TTN Device Address."""
        return self.dev_addr

    @property
    def application_key(self) -> bytearray16:
        """Returns the TTN Application Key."""
        return self.app_key

    @property
    def network_key(self) -> bytearray16:
        """Returns the TTN Network Key."""
        return self.net_key


class TinyLoRa:
    """TinyLoRa Interface"""

    # SPI Write Buffer
    _BUFFER: bytearray2 = bytearray(2)

    def __init__(
        self,
        spi: busio.SPI,
        cs: digitalio.DigitalInOut,
        irq: digitalio.DigitalInOut,
        rst: digitalio.DigitalInOut,
        ttn_config: digitalio.DigitalInOut,
        channel: Optional[int] = None,
    ):
        """Interface for a HopeRF RFM95/6/7/8(w) radio module. Sets module up for sending to
        The Things Network.

        :param ~busio.SPI spi: The SPI bus the device is on
        :param ~digitalio.DigitalInOut cs: Chip select pin (RFM_NSS)
        :param ~digitalio.DigitalInOut irq: RFM's DIO0 Pin (RFM_DIO0)
        :param ~digitalio.DigitalInOut rst: RFM's RST Pin (RFM_RST)
        :param TTN ttn_config: TTN Configuration.
        :param int channel: Frequency Channel.
        """
        self._irq = irq
        self._irq.switch_to_input()
        self._cs = cs
        self._cs.switch_to_output()
        self._rst = rst
        self._rst.switch_to_output()
        # Set up SPI Device on Mode 0
        self._device = adafruit_bus_device.spi_device.SPIDevice(
            spi, self._cs, baudrate=4000000, polarity=0, phase=0
        )
        self._rst.value = False
        time.sleep(0.0001)  # 100 us
        self._rst.value = True
        time.sleep(0.005)  # 5 ms
        # Verify the version of the RFM module
        self._version = self._read_u8(_REG_VERSION)
        if self._version != 18:
            raise TypeError("Can not detect LoRa Module. Please check wiring!")
        # Set Frequency registers
        self._rfm_msb: Optional[registeraddress] = None
        self._rfm_mid: Optional[registeraddress] = None
        self._rfm_lsb: Optional[registeraddress] = None
        # Set datarate registers
        self._sf: Optional[registeraddress] = None
        self._bw: Optional[registeraddress] = None
        self._modemcfg: Optional[registeraddress] = None
        self.set_datarate("SF7BW125")
        # Set regional frequency plan
        if "US" in ttn_config.country:
            from adafruit_tinylora.ttn_usa import TTN_FREQS

            self._frequencies = TTN_FREQS
        elif ttn_config.country == "AS":
            from adafruit_tinylora.ttn_as import TTN_FREQS

            self._frequencies = TTN_FREQS
        elif ttn_config.country == "AU":
            from adafruit_tinylora.ttn_au import TTN_FREQS

            self._frequencies = TTN_FREQS
        elif ttn_config.country == "EU":
            from adafruit_tinylora.ttn_eu import TTN_FREQS

            self._frequencies = TTN_FREQS
        elif ttn_config.country == "CN":
            from adafruit_tinylora.ttn_cn import TTN_FREQS

            self._frequencies = TTN_FREQS
        else:
            raise TypeError("Country Code Incorrect/Unsupported")
        # pylint: enable=import-outside-toplevel
        # Set Channel Number
        self._channel = channel
        self._tx_random = randint(0, 7)
        if self._channel is not None:
            # set single channel
            self.set_channel(self._channel)
        # Init FrameCounter
        self.frame_counter = 0
        # Set up RFM9x for LoRa Mode
        for pair in (
            (_REG_OPERATING_MODE, _MODE_SLEEP),
            (_REG_OPERATING_MODE, _MODE_LORA),
            (_REG_PA_CONFIG, 0xFF),
            (_REG_PREAMBLE_DETECT, 0x25),
            (_REG_PREAMBLE_MSB, 0x00),
            (_REG_PREAMBLE_LSB, 0x08),
            (_REG_MODEM_CONFIG, 0x0C),
            (_REG_TIMER1_COEF, 0x34),
            (_REG_NODE_ADDR, 0x27),
            (_REG_IMAGE_CAL, 0x1D),
            (_REG_RSSI_CONFIG, 0x80),
            (_REG_RSSI_COLLISION, 0x00),
        ):
            self._write_u8(pair[0], pair[1])
        # Give the lora object ttn configuration
        self._ttn_config = ttn_config

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exception_type: Optional[Type[type]],
        exception_value: Optional[BaseException],
        traceback: Optional[TracebackType],
    ) -> None:
        self.deinit()

    def deinit(self) -> None:
        """Deinitializes the TinyLoRa object properties and pins."""
        self._irq = None
        self._rst = None
        self._cs = None
        self.frame_counter = 0
        self._rfm_msb = None
        self._rfm_mid = None
        self._rfm_lsb = None
        self._sf = None
        self._bw = None
        self._modemcfg = None

    def send_data(
        self, data: bytearray, data_length: int, frame_counter: int, timeout: int = 2
    ) -> None:
        """Function to assemble and send data
        :param data: data to send
        :param data_length: length of data to send
        :param frame_counter: frame counter variable, declared in code.py.
        :param timeout: TxDone wait time, default is 2.
        """
        # data packet
        enc_data = bytearray(data_length)
        lora_pkt = bytearray(64)
        # copy bytearray into bytearray for encryption
        enc_data[0:data_length] = data[0:data_length]
        # encrypt data (enc_data is overwritten in this function)
        self.frame_counter = frame_counter
        aes = AES(
            self._ttn_config.device_address,
            self._ttn_config.app_key,
            self._ttn_config.network_key,
            self.frame_counter,
        )
        enc_data = aes.encrypt(enc_data)
        # append preamble to packet
        lora_pkt[0] = const(_REG_DIO_MAPPING_1)
        lora_pkt[1] = self._ttn_config.device_address[3]
        lora_pkt[2] = self._ttn_config.device_address[2]
        lora_pkt[3] = self._ttn_config.device_address[1]
        lora_pkt[4] = self._ttn_config.device_address[0]
        lora_pkt[5] = 0
        lora_pkt[6] = frame_counter & 0x00FF
        lora_pkt[7] = (frame_counter >> 8) & 0x00FF
        lora_pkt[8] = 0x01
        # set length of LoRa packet
        lora_pkt_len = 9
        # load encrypted data into lora_pkt
        lora_pkt[lora_pkt_len : lora_pkt_len + data_length] = enc_data[0:data_length]
        # recalculate packet length
        lora_pkt_len += data_length
        # Calculate MIC
        mic: bytearray4 = bytearray(4)
        mic = aes.calculate_mic(lora_pkt, lora_pkt_len, mic)
        # load mic in package
        lora_pkt[lora_pkt_len : lora_pkt_len + 4] = mic[0:4]
        # recalculate packet length (add MIC length)
        lora_pkt_len += 4
        self.send_packet(lora_pkt, lora_pkt_len, timeout)

    def send_packet(self, lora_packet: bytearray, packet_length: int, timeout: int) -> None:
        """Sends a LoRa packet using the RFM Module
        :param bytearray lora_packet: assembled LoRa packet from send_data
        :param int packet_length: length of LoRa packet to send
        :param int timeout: TxDone wait time.
        """
        # Set RFM to standby
        self._write_u8(_MODE_STDBY, 0x81)
        # wait for RFM to enter standby mode
        time.sleep(0.01)
        # switch interrupt to txdone
        self._write_u8(0x40, 0x40)
        # check for multi-channel configuration
        if self._channel is None:
            self._tx_random = randint(0, 7)
            self._rfm_lsb = self._frequencies[self._tx_random][2]
            self._rfm_mid = self._frequencies[self._tx_random][1]
            self._rfm_msb = self._frequencies[self._tx_random][0]
        # Set up frequency registers
        for pair in (
            (_REG_FRF_MSB, self._rfm_msb),
            (_REG_FRF_MID, self._rfm_mid),
            (_REG_FRF_LSB, self._rfm_lsb),
            (_REG_FEI_LSB, self._sf),
            (_REG_FEI_MSB, self._bw),
            (_REG_MODEM_CONFIG, self._modemcfg),
            (_REG_PAYLOAD_LENGTH, packet_length),
            (_REG_FIFO_POINTER, _REG_FIFO_BASE_ADDR),
        ):
            self._write_u8(pair[0], pair[1])
        # fill the FIFO buffer with the LoRa payload
        for packet_index in range(packet_length):
            self._write_u8(0x00, lora_packet[packet_index])
        # switch RFM to TX operating mode
        self._write_u8(_REG_OPERATING_MODE, _MODE_TX)
        # wait for TxDone IRQ, poll for timeout.
        start = time.monotonic()
        timed_out = False
        while not timed_out and not self._irq.value:
            if (time.monotonic() - start) >= timeout:
                timed_out = True
        # switch RFM to sleep operating mode
        self._write_u8(_REG_OPERATING_MODE, _MODE_SLEEP)
        if timed_out:
            raise RuntimeError("Timeout during packet send")

    def set_datarate(self, datarate: str) -> None:
        """Sets the RFM Datarate
        :param datarate: Bandwidth and Frequency Plan
        """
        # TODO: Convert these to enum
        data_rates = {
            "SF7BW125": (0x74, 0x72, 0x04),
            "SF7BW250": (0x74, 0x82, 0x04),
            "SF8BW125": (0x84, 0x72, 0x04),
            "SF9BW125": (0x94, 0x72, 0x04),
            "SF10BW125": (0xA4, 0x72, 0x04),
            "SF11BW125": (0xB4, 0x72, 0x0C),
            "SF12BW125": (0xC4, 0x72, 0x0C),
        }
        try:
            self._sf, self._bw, self._modemcfg = data_rates[datarate]
        except KeyError as err:
            raise KeyError("Invalid or Unsupported Datarate.") from err

    def set_channel(self, channel: int) -> None:
        """Sets the RFM Channel (if single-channel)
        :param int channel: Transmit Channel (0 through 7).
        """
        self._rfm_msb, self._rfm_mid, self._rfm_lsb = self._frequencies[channel]

    def _read_into(
        self, address: registeraddress, buf: bytearray2, length: Optional[int] = None
    ) -> None:
        """Read a number of bytes from the specified address into the
        provided buffer. If length is not specified (default) the entire buffer
        will be filled.
        :param bytearray address: Register Address.
        :param bytearray buf: Data Buffer for bytes.
        :param int length: Buffer length.
        """
        if length is None:
            length = len(buf)
        with self._device as device:
            # Strip out top bit to set 0 value (read).
            self._BUFFER[0] = address & 0x7F
            device.write(self._BUFFER, end=1)
            device.readinto(buf, end=length)

    def _read_u8(self, address: registeraddress) -> int:
        """Read a single byte from the provided address and return it.
        :param bytearray address: Register Address.
        """
        self._read_into(address, self._BUFFER, length=1)
        return self._BUFFER[0]

    def _write_u8(self, address: registeraddress, val: int) -> None:
        """Writes to the RFM register given an address and data.
        :param bytearray address: Register Address.
        :param val: Data to write.
        """
        with self._device as device:
            self._BUFFER[0] = address | 0x80  # MSB 1 to Write
            self._BUFFER[1] = val
            device.write(self._BUFFER, end=2)
