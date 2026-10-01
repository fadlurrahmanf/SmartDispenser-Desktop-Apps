#include <stdbool.h>
#include <stdint.h>

#include "stm32l071xx.h"

static volatile uint32_t milliseconds;
void SysTick_Handler(void) { ++milliseconds; }

static void delay_ms(uint32_t duration)
{
    const uint32_t start = milliseconds;
    while ((uint32_t)(milliseconds - start) < duration) { }
}

static void delay_cycles(volatile uint32_t cycles)
{
    while (cycles-- != 0u) { __NOP(); }
}

static void led_set(bool on)
{
    if (on) GPIOC->BSRR = (1u << 29u);
    else GPIOC->BSRR = (1u << 13u);
}

static void flash(uint32_t count)
{
    while (count-- != 0u) {
        led_set(true); delay_ms(1000u);
        led_set(false); delay_ms(250u);
    }
}

/* Slow GPIO I2C probe: START + 7-bit address + write bit + STOP only. */
static void sda_release(void) { GPIOB->BSRR = (1u << 9u); }
static void sda_low(void)     { GPIOB->BSRR = (1u << 25u); }
static void scl_release(void) { GPIOB->BSRR = (1u << 8u); }
static void scl_low(void)     { GPIOB->BSRR = (1u << 24u); }
static bool sda_read(void)    { return (GPIOB->IDR & (1u << 9u)) != 0u; }
static bool scl_read(void)    { return (GPIOB->IDR & (1u << 8u)) != 0u; }

static bool scl_high(void)
{
    scl_release();
    for (uint32_t timeout = 0u; timeout < 10000u; ++timeout) {
        if (scl_read()) return true;
    }
    return false;
}

static void i2c_start(void)
{
    sda_release(); scl_release(); delay_cycles(80u);
    sda_low(); delay_cycles(80u); scl_low();
}

static void i2c_stop(void)
{
    sda_low(); delay_cycles(80u); scl_high(); delay_cycles(80u);
    sda_release(); delay_cycles(80u);
}

static bool i2c_send_byte(uint8_t value)
{
    for (uint8_t bit = 0u; bit < 8u; ++bit) {
        if ((value & 0x80u) != 0u) sda_release(); else sda_low();
        delay_cycles(80u);
        if (!scl_high()) return false;
        delay_cycles(80u);
        scl_low();
        value <<= 1;
    }
    sda_release(); delay_cycles(80u);
    if (!scl_high()) return false;
    delay_cycles(80u);
    const bool acknowledged = !sda_read();
    scl_low();
    return acknowledged;
}

static bool i2c_probe(uint8_t address)
{
    i2c_start();
    const bool acknowledged = i2c_send_byte((uint8_t)(address << 1));
    i2c_stop();
    return acknowledged;
}

static void signal_nibble(uint8_t value)
{
    if (value == 0u) {
        led_set(true); delay_ms(2000u); led_set(false); delay_ms(250u);
    } else {
        flash(value);
    }
}

int main(void)
{
    RCC->IOPENR |= RCC_IOPENR_GPIOBEN | RCC_IOPENR_GPIOCEN;
    GPIOC->MODER = (GPIOC->MODER & ~(3u << 26u)) | (1u << 26u);
    GPIOC->OTYPER &= ~(1u << 13u);

    GPIOB->MODER = (GPIOB->MODER & ~((3u << 16u) | (3u << 18u))) | (1u << 16u) | (1u << 18u);
    GPIOB->OTYPER |= (1u << 8u) | (1u << 9u);
    GPIOB->PUPDR &= ~((3u << 16u) | (3u << 18u));
    sda_release();
    scl_release();

    SystemCoreClockUpdate();
    SysTick_Config(SystemCoreClock / 1000u);
    flash(3u);
    delay_ms(1500u);

    while (true) {
        uint8_t found[8];
        uint8_t found_count = 0u;
        for (uint8_t address = 0x08u; address <= 0x77u; ++address) {
            if (i2c_probe(address) && found_count < (uint8_t)sizeof(found)) {
                found[found_count++] = address;
            }
        }

        if (found_count == 0u) {
            flash(2u); /* no ACK on the complete normal I2C address range */
            delay_ms(3000u);
            continue;
        }

        for (uint8_t index = 0u; index < found_count; ++index) {
            const uint8_t address = found[index];
            signal_nibble((uint8_t)(address >> 4));
            delay_ms(1200u);
            signal_nibble((uint8_t)(address & 0x0Fu));
            delay_ms(3000u);
        }
    }
}
