#!/usr/bin/env python3
#
# Reverse : Generate an indented asm code (pseudo-C) with colored syntax.
# Copyright (C) 2015    Joel
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.    See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.    If not, see <http://www.gnu.org/licenses/>.
#

import struct

from reverse import lib
from reverse.lib.custom_colors import *
from reverse.lib.utils import print_no_end, get_char, BYTES_PRINTABLE_SET
from reverse.lib.colors import color, bold
from reverse.lib.fileformat.binary import T_BIN_RAW
from reverse.lib.memory import MEM_CODE, MEM_UNK, MEM_FUNC
from reverse.lib.disassembler import FUNC_FLAG_NORETURN


class OutputAbs():
    def __init__(self, ctx=None):
        self.token_lines = [] # each line is separated in tokens (string, color, is_bold)
        self.lines = [] # each line contains the entire string
        self.line_addr = {} # line -> address
        self.addr_line = {} # address -> line
        self.index_end_inst = {} # line -> (char_index, token_index)
        self.curr_index = 0

        self.section_prefix = False
        self.curr_section = None # must be updated at hand !!
        self.print_labels = True

        # Easy accesses
        self._dis = ctx.gctx.dis
        self._binary = self._dis.binary
        self.gctx = ctx.gctx
        self.ctx = ctx


    # All functions which start with a '_' add a new token/string on
    # the current line.

    def get_inst_str(self, i):
        if len(i.operands) == 0:
            return i.mnemonic
        return "%s %s" % (i.mnemonic, i.op_str)


    def inst_end_here(self):
        # save a tuple (a, b)
        # a: index (in self.lines[i]) of the last character of an instruction.
        # b: index (in self.token_lines[i]) of the last token.
        line = len(self.token_lines)-1
        self.index_end_inst[line] = \
            (self.curr_index, len(self.token_lines[line]))

    def is_last_2_line_empty(self):
        if len(self.lines) < 2:
            return True
        return len(self.lines[-1]) == 0 and len(self.lines[-2]) == 0

    def _new_line(self):
        self.curr_index = 0
        self.token_lines.append([])
        self.lines.append([])

    def _add(self, string):
        self.token_lines[-1].append((string, 0, False))
        self.lines[-1].append(string)
        self.curr_index += len(string)

    def _pad_width(self, w):
        if self.curr_index != w:
            self._add(" " * (w - self.curr_index))

    def _tabs(self, tab):
        # debug
        # if not self.token_lines[-1]:
            # self.token_lines[-1].append(("       ", 0, False))
        t = tab * "    "
        self.token_lines[-1].append((t, 0, False))
        self.lines[-1].append(t)
        self.curr_index += len(t)

    def _comment(self, string):
        self.token_lines[-1].append((string, COLOR_COMMENT.val, COLOR_COMMENT.bold))
        self.lines[-1].append(string)
        self.curr_index += len(string)

    def _address(self, addr, print_colon=True, normal_color=False, notprefix=False):
        if self.section_prefix and not notprefix:
            self._comment(self.curr_section.name)
            self._add(" ")

        s = hex(addr)
        if print_colon:
            s += ": "

        if not normal_color and addr in self.ctx.addr_color:
            col = self.ctx.addr_color[addr]
        else:
            if notprefix:
                col = 0
            else:
                col = COLOR_ADDR.val

        self.token_lines[-1].append((s, col, False))
        self.lines[-1].append(s)
        self.curr_index += len(s)

    def _type(self, string):
        self.token_lines[-1].append((string, COLOR_TYPE.val, COLOR_TYPE.bold))
        self.lines[-1].append(string)
        self.curr_index += len(string)

    def _variable(self, string):
        self.token_lines[-1].append((string, COLOR_VAR.val, COLOR_VAR.bold))
        self.lines[-1].append(string)
        self.curr_index += len(string)

    def _keyword(self, string):
        self.token_lines[-1].append((string, COLOR_KEYWORD.val, COLOR_KEYWORD.bold))
        self.lines[-1].append(string)
        self.curr_index += len(string)

    def _string(self, string):
        self.token_lines[-1].append((string, COLOR_STRING.val, COLOR_STRING.bold))
        self.lines[-1].append(string)
        self.curr_index += len(string)

    def _section(self, string):
        self.token_lines[-1].append((string, COLOR_SECTION.val, COLOR_SECTION.bold))
        self.lines[-1].append(string)
        self.curr_index += len(string)

    def _internal_comment(self, string):
        self.token_lines[-1].append((string, COLOR_INTERN_COMMENT.val, COLOR_INTERN_COMMENT.bold))
        self.lines[-1].append(string)
        self.curr_index += len(string)

    def _user_comment(self, string):
        self.token_lines[-1].append((string, COLOR_USER_COMMENT.val, COLOR_USER_COMMENT.bold))
        self.lines[-1].append(string)
        self.curr_index += len(string)

    def _retcall(self, string):
        self.token_lines[-1].append((string, COLOR_RETCALL.val, COLOR_RETCALL.bold))
        self.lines[-1].append(string)
        self.curr_index += len(string)

    def _db(self, by):
        self._retcall(".db")
        if by is None:
            self._add(" ?")
        else:
            self._add(" %0.2x" % by)
            if by in BYTES_PRINTABLE_SET:
                self._string("  '%c'" % by)


    def _label(self, ad, tab=-1, print_colon=True, nocolor=False):
        l = None
        is_sym = False

        ty = self._dis.mem.get_type(ad)

        if ad in self.gctx.db.reverse_symbols:
            l = str(self.gctx.db.reverse_symbols[ad])
            col = COLOR_SYMBOL.val
            is_sym = True
        elif ad not in self._dis.xrefs and ty != MEM_FUNC:
            return False

        if ty == MEM_FUNC:
            if l is None:
                l = "sub_%x" % ad
            col = COLOR_SYMBOL.val

        elif ty == MEM_CODE:
            if self.ctx.is_dump:
                if l is None:
                    l = "loc_%x" % ad
                col = COLOR_CODE_ADDR.val
            else:
                if not is_sym:
                    return False
                col = COLOR_ADDR.val

        elif ty == MEM_UNK:
            if l is None:
                l = "unk_%x" % ad
            col = COLOR_UNK.val

        elif not is_sym:
            return False

        if print_colon:
            l += ":"

        # TODO: keep all colors in decompilation mode ?
        if not self.ctx.is_dump:
            if ad in self.ctx.addr_color:
                col = self.ctx.addr_color[ad]
            else:
                if is_sym or ty == MEM_FUNC:
                    if l.startswith("loop_") or l.startswith("ret_"):
                        col = COLOR_ADDR.val
                    else:
                        col = COLOR_SYMBOL.val
                else:
                    col = 0
                    
        if nocolor:
            col = 0

        if tab == -1:
            self.token_lines[-1].append((l, col, False))
            self.lines[-1].append(l)
            self.curr_index += len(l)
        else:
            self._tabs(tab)

            if ty == MEM_FUNC:
                flags = self.gctx.dis.functions[ad][1]
                if flags & FUNC_FLAG_NORETURN:
                    self._comment("__noreturn__ ")

            self.token_lines[-1].append((l, col, False))
            self.lines[-1].append(l)
            self.curr_index += len(l)

        return True


    def _label_or_address(self, addr, tab=-1, print_colon=True):
        if self._label(addr, tab, print_colon):
            return
        self._tabs(tab)
        self._address(addr, print_colon)


    def _label_and_address(self, ad, tab=-1, print_colon=True, with_comment=False):
        is_first = not self.ctx.is_dump and ad == self.ctx.entry

        if not is_first and self._label(ad, tab, print_colon):
            self._new_line()
            if tab != -1:
                self._tabs(tab)
            if with_comment:
                self._comment("# ")
            self._address(ad, print_colon, True)
        else:
            if tab != -1:
                self._tabs(tab)
            if with_comment:
                self._comment("# ")
            self._address(ad, print_colon)


    def _previous_comment(self, i, tab):
        if i.address in self._dis.internal_previous_comments:
            if self.ctx.is_dump and not self.is_last_2_line_empty():
                self._new_line()
            for comm in self._dis.internal_previous_comments[i.address]:
                self._tabs(tab)
                self._internal_comment("; %s" % comm)
                self._new_line()

        if i.address in self._dis.user_previous_comments:
            if self.ctx.is_dump and not self.is_last_2_line_empty():
                self._new_line()
            for comm in self._dis.user_previous_comments[i.address]:
                self._tabs(tab)
                self._user_comment("; %s" % comm)
                self._new_line()


    def _commented_inst(self, i, tab):
        self._label_and_address(i.address, tab, with_comment=True)
        self.set_line(i.address)
        self._bytes(i, True)
        self._comment(self.get_inst_str(i))
        self._inline_comment(i)
        self._new_line()


    def _inline_comment(self, i):
        self.inst_end_here()
        if i.address in self._dis.user_inline_comments:
            self._add(" ")
            self._user_comment("; %s" %
                    self._dis.user_inline_comments[i.address])
        if i.address in self._dis.internal_inline_comments:
            self._add(" ")
            self._internal_comment("; %s" %
                    self._dis.internal_inline_comments[i.address])


    # Only used when --nocomment is enabled and a jump point to this instruction
    def _address_if_needed(self, i, tab):
        if i.address in self.ctx.addr_color:
            self._tabs(tab)
            self._address(i.address)


    def _bytes(self, i, comment_this=False):
        if self.gctx.print_bytes:
            if comment_this:
                if self.gctx.comments:
                    for c in i.bytes:
                        self._comment("%x " % c)
            else:
                for c in i.bytes:
                    self._comment("%.2x " % c)


    def _comment_fused(self, jump_inst, fused_inst, tab):
        if self.gctx.comments:
            if fused_inst != None:
                self._asm_inst(fused_inst, tab, "# ")
            if jump_inst != None:
                self._asm_inst(jump_inst, tab, "# ")
        else:
            # Otherwise print only the address if referenced
            if fused_inst != None:
                self._address_if_needed(fused_inst, tab)
            if jump_inst != None:
                self._address_if_needed(jump_inst, tab)


    def _all_vars(self):
        idx = 0
        for sz in self.ctx.local_vars_size:
            name = self.ctx.local_vars_name[idx]
            self._tabs(1)
            self._type("int%d_t " % (sz*8))
            self._variable(name)
            self._new_line()
            idx += 1


    def _asm_block(self, blk, tab):
        for i in blk:
            self._asm_inst(i, tab)


    def _bad(self, addr, tab=0):
        self._tabs(tab)
        self._address(addr)
        self._add("(bad)")
        self._new_line()


    def _dash(self):
        self._user_comment("; ---------------------------------------------------------------------")
        self._new_line()

    #
    # Print an immediate value
    # imm         the immediate to print
    # op_size     op.size is not available in arm, so it's in arguments
    # hexa        print in hexa if no symbol or something else was found
    # section     the section where `imm` is, if None a search will be done
    # print_data  print the string at the address `imm` only if `imm` is not a symbol
    # force_dont_print_data  really don't print data even if it's not a symbol
    #                        it's used for jump/call
    #
    def _imm(self, imm, op_size, hexa, section=None, print_data=True,
             force_dont_print_data=False):

        if self.gctx.capstone_string:
            hexa = True

        label_printed = self._label(imm, print_colon=False)

        if label_printed:
            ty = self._dis.mem.get_type(imm)
            # ty == -1 : from the terminal (with -x) there are no xrefs
            if imm in self._dis.xrefs and ty != MEM_UNK or ty == -1:
                return True

        if section is None:
            section = self._binary.get_section(imm)

        # For a raw file, if the raw base is 0 the immediate is considered
        # as an address only if it's in the symbols list.
        raw_base_zero = self._binary.type == T_BIN_RAW and self.gctx.raw_base == 0

        if section is not None and not raw_base_zero:
            if not label_printed:
                self._address(imm, print_colon=False, notprefix=True)

            if not force_dont_print_data and \
                    print_data and imm not in self._binary.reverse_symbols and \
                    section is not None and section.is_data:
                s = self._binary.get_string(imm, self.gctx.max_data_size)
                if s != "\"\"":
                    self._add(" ")
                    self._string(s)

            return True

        elif op_size == 1:
            self._string("'%s'" % get_char(imm))
        elif hexa:
            self._add(hex(imm))
        else:
            self._add(str(imm))

            if imm > 0:
                if op_size == 4:
                    packed = struct.pack("<L", imm)
                elif op_size == 8:
                    packed = struct.pack("<Q", imm)
                else:
                    return True
                if set(packed).issubset(BYTES_PRINTABLE_SET):
                    self._string(" \"" + "".join(map(chr, packed)) + "\"")
                    return False

            # returns True because capstone print immediate in hexa and
            # it will be printed in a comment, sometimes it's better
            # to have the value in hexa
            return True

        return False


    def set_line(self, addr):
        l = len(self.token_lines) - 1
        self.line_addr[l] = addr
        if addr not in self.addr_line or l < self.addr_line[addr]:
            self.addr_line[addr] = l


    def is_label(self, ad):
        return ad in self._binary.reverse_symbols or \
               ad in self._dis.xrefs


    def var_name_exists(self, i, op_num):
        return i.operands[op_num].mem.disp in self.ctx.local_vars_idx


    def get_var_name(self, i, op_num):
        idx = self.ctx.local_vars_idx[i.operands[op_num].mem.disp]
        return self.ctx.local_vars_name[idx]


    def _ast(self, entry, ast):
        self._new_line()
        self._keyword("function ")

        if not self._label(entry, print_colon=False, nocolor=True):
            self._add(hex(entry))

        section = self._binary.get_section(entry)

        if section is not None:
            self._add(" (")
            self._section(section.name)
            self._add(") {")
        else:
            self._add(" {")

        self._new_line()
        self._all_vars()
        ast.dump(self, 1)
        self._add("}")
        self.join_lines()


    def join_lines(self):
        # Join all lines
        for i, l in enumerate(self.lines):
            self.lines[i] = "".join(self.lines[i])
            sz = len(self.lines[i])
            if i not in self.index_end_inst:
                self.index_end_inst[i] = (sz + 1, len(l))


    def _asm_inst(self, i, tab=0, prefix=""):
        self._previous_comment(i, tab)

        if prefix == "# ":
            # debug
            # from lib.utils import BRANCH_NEXT
            # if i.address in self.ctx.gph.link_out:
                # self._add(hex(self.ctx.gph.link_out[i.address][BRANCH_NEXT]))
            self._commented_inst(i, tab)
            return

        if i.address in self.ctx.all_fused_inst:
            return

        if self.print_labels:
            self._label_and_address(i.address, tab)
            self._bytes(i)
        else:
            self._tabs(tab)
            self._address(i.address)

        self.set_line(i.address)

        # debug
        # from lib.utils import BRANCH_NEXT
        # if i.address in self.ctx.gph.link_out:
            # self._add(hex(self.ctx.gph.link_out[i.address][BRANCH_NEXT]))

        modified = self._sub_asm_inst(i, tab, prefix)

        self._inline_comment(i)
        self._new_line()


    def print(self):
        for l in self.token_lines:
            for (string, col, is_bold) in l:
                if self.gctx.color:
                    if col != 0:
                        string = color(string, col)
                    if is_bold:
                        string = bold(string)
                print_no_end(string)
            print()


    # Return True if the operand is a variable (because the output is
    # modified, we reprint the original instruction later)
    def _operand(self, i, num_op, hexa=False, show_deref=True):
        raise NotImplementedError


    def _if_cond(self, jump_id, jump_cond, fused_inst):
        raise NotImplementedError


    # Architecture specific output
    def _sub_asm_inst(self, i, tab=0, prefix=""):
        raise NotImplementedError
