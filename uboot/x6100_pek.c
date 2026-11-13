// SPDX-License-Identifier: GPL-2.0+
/*
 * pek: the X6100's POWER key (the AXP223 PMIC's PEK) in the boot menu.
 *
 * The AXP223 latches a short press of its key in IRQ status register 3 (0x4A) bit 1 and a long
 * one in bit 0 (Linux's drivers/mfd/axp20x.c: AXP22X PEK_SHORT 2,1 and PEK_LONG 2,0); writing 1
 * clears a bit. The two are enabled in IRQ enable register 3 (0x42) so that they latch.
 *
 *   pek clear   clears both (the press that switched the radio on); always true
 *   pek         true once after a short press since the last call
 */
#include <command.h>
#include <asm/arch/pmic_bus.h>

#define AXP_IRQ_ENABLE3 0x42
#define AXP_IRQ_STATUS3 0x4a
#define PEK_SHORT       0x02
#define PEK_LONG        0x01

static int do_pek(struct cmd_tbl *cmdtp, int flag, int argc, char *const argv[])
{
	u8 st;

	if (argc > 1) {
		pmic_bus_setbits(AXP_IRQ_ENABLE3, PEK_SHORT | PEK_LONG);
		pmic_bus_write(AXP_IRQ_STATUS3, PEK_SHORT | PEK_LONG);
		return CMD_RET_SUCCESS;
	}
	if (pmic_bus_read(AXP_IRQ_STATUS3, &st))
		return CMD_RET_FAILURE;
	if (st & (PEK_SHORT | PEK_LONG))
		pmic_bus_write(AXP_IRQ_STATUS3, st & (PEK_SHORT | PEK_LONG));
	return (st & PEK_SHORT) ? CMD_RET_SUCCESS : CMD_RET_FAILURE;
}

U_BOOT_CMD(pek, 2, 0, do_pek, "X6100 POWER key: true once after a short press",
	   "        - true if the key was pressed since the last call\npek clear  - forget earlier presses");
