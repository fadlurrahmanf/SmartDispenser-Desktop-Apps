#include <stdbool.h>
#include <stdint.h>

#include "stm32l071xx.h"

/* J1: SDA=PB9 and SCL=PB8. Bench scan found an ACK at 0x26. */
#define LCD_ADDRESS    0x26u
#define LCD_BACKLIGHT  (1u << 3)
#define LCD_ENABLE     (1u << 2)
#define LCD_RS         (1u << 0)

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
    if (on) GPIOC->BSRR = (1u << 29u); /* PC13 active LOW */
    else GPIOC->BSRR = (1u << 13u);
}

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

static bool lcd_expander_write(uint8_t value)
{
    i2c_start();
    const bool address_ack = i2c_send_byte((uint8_t)(LCD_ADDRESS << 1));
    const bool data_ack = address_ack && i2c_send_byte(value);
    i2c_stop();
    return data_ack;
}

/* Common PCF8574 mapping: P0=RS, P2=EN, P3=BL, P4..P7=D4..D7. */
static bool lcd_nibble(uint8_t nibble, bool data_register)
{
    const uint8_t value = (uint8_t)((nibble << 4) | LCD_BACKLIGHT |
                                    (data_register ? LCD_RS : 0u));
    return lcd_expander_write((uint8_t)(value | LCD_ENABLE)) &&
           lcd_expander_write(value);
}

static bool lcd_byte(uint8_t value, bool data_register)
{
    return lcd_nibble((uint8_t)(value >> 4), data_register) &&
           lcd_nibble((uint8_t)(value & 0x0Fu), data_register);
}

static bool lcd_command(uint8_t command)
{
    const bool result = lcd_byte(command, false);
    delay_ms((command == 0x01u || command == 0x02u) ? 3u : 1u);
    return result;
}

static bool lcd_print(const char *text)
{
    while (*text != '\0') {
        if (!lcd_byte((uint8_t)*text++, true)) return false;
        delay_ms(1u);
    }
    return true;
}

static bool lcd_init(void)
{
    delay_ms(50u);
    if (!lcd_nibble(0x03u, false)) return false;
    delay_ms(5u);
    if (!lcd_nibble(0x03u, false)) return false;
    delay_ms(2u);
    if (!lcd_nibble(0x03u, false)) return false;
    if (!lcd_nibble(0x02u, false)) return false;
    return lcd_command(0x28u) && lcd_command(0x08u) &&
           lcd_command(0x01u) && lcd_command(0x06u) && lcd_command(0x0Cu);
}

static void error_pattern(void)
{
    while (true) {
        led_set(true); delay_ms(250u); led_set(false); delay_ms(250u);
        led_set(true); delay_ms(250u); led_set(false); delay_ms(1500u);
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

    if (!lcd_init() || !lcd_command(0x80u) || !lcd_print("SmartDispenser") ||
        !lcd_command(0xC0u) || !lcd_print("LCD I2C OK")) error_pattern();

    while (true) {
        led_set(true); delay_ms(500u);
        led_set(false); delay_ms(500u);
    }
}
