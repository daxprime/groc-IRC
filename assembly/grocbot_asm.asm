; groc-IRC Assembly Routines - x86_64 NASM (ELF64)
; High-performance IRC parsing, sanitization, XOR cipher, DJB2 hash, rate check
; Build: nasm -f elf64 grocbot_asm.asm -o grocbot_asm.o && gcc -shared -o grocbot_asm.so grocbot_asm.o -nostartfiles

section .data
    align 8

section .bss
    align 8

section .text
    global fast_irc_parse
    global sanitize_buffer
    global xor_encrypt
    global hash_djb2
    global rate_check

; ============================================================================
; fast_irc_parse(const char *input, char *output, int len)
; Parses IRC line into struct: prefix[128] command[32] params[256] trailing[96]
; Returns 0 on success, -1 on error
; ============================================================================
fast_irc_parse:
    push rbp
    mov rbp, rsp
    push rbx
    push r12
    push r13
    push r14
    push r15

    mov r12, rdi            ; input
    mov r13, rsi            ; output buffer (512 bytes)
    mov r14d, edx           ; input length

    ; Clear output buffer
    mov rdi, r13
    xor eax, eax
    mov ecx, 512
    rep stosb

    ; Check if starts with ':'  (prefix)
    mov rsi, r12
    cmp byte [rsi], ':'
    jne .no_prefix

    ; Parse prefix
    inc rsi                 ; skip ':'
    lea rdi, [r13]          ; output.prefix
    xor ecx, ecx
.prefix_loop:
    cmp ecx, 127
    jge .prefix_done
    mov al, [rsi]
    cmp al, ' '
    je .prefix_done
    cmp al, 0
    je .prefix_done
    mov [rdi + rcx], al
    inc rsi
    inc ecx
    jmp .prefix_loop
.prefix_done:
    cmp byte [rsi], ' '
    jne .no_prefix
    inc rsi                 ; skip space

.no_prefix:
    ; Parse command
    lea rdi, [r13 + 128]    ; output.command
    xor ecx, ecx
.cmd_loop:
    cmp ecx, 31
    jge .cmd_done
    mov al, [rsi]
    cmp al, ' '
    je .cmd_done
    cmp al, 0
    je .parse_end
    mov [rdi + rcx], al
    inc rsi
    inc ecx
    jmp .cmd_loop
.cmd_done:
    cmp byte [rsi], ' '
    jne .parse_end
    inc rsi

    ; Parse params (check for trailing ' :')
    lea rdi, [r13 + 160]    ; output.params
    lea r15, [r13 + 416]    ; output.trailing
    xor ecx, ecx
.params_loop:
    cmp ecx, 255
    jge .parse_end
    mov al, [rsi]
    cmp al, 0
    je .parse_end

    ; Check for ' :' (trailing marker)
    cmp al, ':'
    jne .not_trailing
    cmp ecx, 0
    je .not_trailing
    cmp byte [rsi - 1], ' '
    jne .not_trailing

    ; Found trailing, copy rest
    dec ecx                 ; remove the space before ':'
    mov byte [rdi + rcx], 0
    inc rsi                 ; skip ':'
    xor ecx, ecx
.trailing_loop:
    cmp ecx, 95
    jge .parse_end
    mov al, [rsi]
    cmp al, 0
    je .parse_end
    cmp al, 13              ; CR
    je .parse_end
    cmp al, 10              ; LF
    je .parse_end
    mov [r15 + rcx], al
    inc rsi
    inc ecx
    jmp .trailing_loop

.not_trailing:
    mov [rdi + rcx], al
    inc rsi
    inc ecx
    jmp .params_loop

.parse_end:
    xor eax, eax            ; return 0 (success)

    pop r15
    pop r14
    pop r13
    pop r12
    pop rbx
    pop rbp
    ret

; ============================================================================
; sanitize_buffer(char *buf, int len)
; Removes non-printable chars (keeps 0x20-0x7E, tab, newline)
; Returns new length
; ============================================================================
sanitize_buffer:
    push rbp
    mov rbp, rsp
    push rbx

    mov rdi, rdi            ; buf (already in rdi)
    mov ecx, esi            ; len
    xor edx, edx            ; write index
    xor ebx, ebx            ; read index

.sanitize_loop:
    cmp ebx, ecx
    jge .sanitize_done
    movzx eax, byte [rdi + rbx]

    ; Check printable range (32-126)
    cmp al, 32
    jl .check_special
    cmp al, 126
    jle .keep_char
    jmp .skip_char

.check_special:
    cmp al, 9               ; tab
    je .keep_char
    cmp al, 10              ; newline
    je .keep_char
    jmp .skip_char

.keep_char:
    mov [rdi + rdx], al
    inc edx
.skip_char:
    inc ebx
    jmp .sanitize_loop

.sanitize_done:
    mov byte [rdi + rdx], 0 ; null terminate
    mov eax, edx            ; return new length

    pop rbx
    pop rbp
    ret

; ============================================================================
; xor_encrypt(char *data, int data_len, const char *key, int key_len)
; XOR encrypts data in-place with repeating key
; ============================================================================
xor_encrypt:
    push rbp
    mov rbp, rsp
    push rbx

    mov r8, rdi             ; data
    mov r9d, esi            ; data_len
    mov r10, rdx            ; key
    mov r11d, ecx           ; key_len

    test r11d, r11d
    jz .xor_done

    xor ebx, ebx            ; index
.xor_loop:
    cmp ebx, r9d
    jge .xor_done

    ; key_index = i % key_len
    mov eax, ebx
    xor edx, edx
    div r11d                ; eax = i / key_len, edx = i % key_len

    movzx eax, byte [r8 + rbx]
    movzx ecx, byte [r10 + rdx]
    xor eax, ecx
    mov [r8 + rbx], al

    inc ebx
    jmp .xor_loop

.xor_done:
    pop rbx
    pop rbp
    ret

; ============================================================================
; hash_djb2(const char *str)
; DJB2 hash function, returns uint64
; ============================================================================
hash_djb2:
    push rbp
    mov rbp, rsp

    mov rsi, rdi            ; str
    mov rax, 5381           ; hash = 5381

.hash_loop:
    movzx ecx, byte [rsi]
    test cl, cl
    jz .hash_done

    ; hash = hash * 33 + c = (hash << 5) + hash + c
    mov rdx, rax
    shl rdx, 5
    add rax, rdx
    movzx ecx, cl
    add rax, rcx
    inc rsi
    jmp .hash_loop

.hash_done:
    pop rbp
    ret

; ============================================================================
; rate_check(uint64 user_hash, uint64 current_time, uint64 max_requests, uint64 window)
; Simple rate check stub - returns 1 (allowed) or 0 (denied)
; In a real implementation, would use shared memory for tracking
; This is a placeholder that always returns 1 (allowed)
; ============================================================================
rate_check:
    push rbp
    mov rbp, rsp

    ; Placeholder: always allow
    ; Real implementation would track per-user request counts
    mov eax, 1

    pop rbp
    ret
