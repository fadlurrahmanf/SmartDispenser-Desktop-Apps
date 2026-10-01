#include <stdint.h>

#include "stm32l0xx.h"

/*
 * LED1 on the STM32 module is wired from VCC through its resistor to PC13.
 * PC13 LOW turns the LED on; PC13 HIGH turns it off.
 */
#define LED_PIN 13u

static void delay_cycles(volatile uint32_t cycles)
{
    while (cycles-- != 0u) {
        __NOP();
    }
}

int main(void)
{
    RCC->IOPENR |= RCC_IOPENR_GPIOCEN;

    GPIOC->MODER = (GPIOC->MODER & ~(3u << (LED_PIN * 2u))) |
                   (1u << (LED_PIN * 2u));
    GPIOC->OTYPER &= ~(1u << LED_PIN);
    GPIOC->PUPDR &= ~(3u << (LED_PIN * 2u));

    for (;;) {
        GPIOC->BSRR = 1u << (LED_PIN + 16u);
        delay_cycles(800000u);

        GPIOC->BSRR = 1u << LED_PIN;
        delay_cycles(800000u);
    }
}

