# groc-IRC Eggdrop Script - Load in eggdrop.conf with: source /path/to/grocbot_eggdrop.tcl

package require http
package require json

namespace eval ::grocbot_egg {
    variable bridge_url "http://127.0.0.1:5580"
    variable prefix "!"
    variable rate_data
    variable rate_limit 5
    variable rate_window 60
    array set rate_data {}

    # Rate check
    proc check_rate {hostmask} {
        variable rate_data
        variable rate_limit
        variable rate_window
        set now [clock seconds]

        if {![info exists rate_data($hostmask)]} {
            set rate_data($hostmask) [list $now]
            return 1
        }

        set times {}
        foreach t $rate_data($hostmask) {
            if {$now - $t < $rate_window} {
                lappend times $t
            }
        }
        if {[llength $times] >= $rate_limit} {
            set rate_data($hostmask) $times
            return 0
        }
        lappend times $now
        set rate_data($hostmask) $times
        return 1
    }

    # Sanitize input
    proc sanitize {text {maxlen 500}} {
        set clean ""
        set len 0
        foreach ch [split $text ""] {
            if {$len >= $maxlen} break
            set code [scan $ch %c]
            if {$code >= 32 && $code <= 126} {
                append clean $ch
                incr len
            }
        }
        return $clean
    }

    # Call bridge API
    proc bridge_chat {channel user message} {
        variable bridge_url
        set url "$bridge_url/api/chat"
        set body [::json::write object \
            channel [::json::write string $channel] \
            user [::json::write string $user] \
            message [::json::write string $message]]

        if {[catch {
            set token [::http::geturl $url -method POST \
                -type "application/json" \
                -query $body -timeout 30000]
            set data [::http::data $token]
            ::http::cleanup $token
            set parsed [::json::json2dict $data]
            if {[dict exists $parsed content]} {
                return [dict get $parsed content]
            }
            return "API Error"
        } err]} {
            return "Bridge error: $err"
        }
    }

    # Set mode via bridge
    proc bridge_set_mode {channel mode} {
        variable bridge_url
        set url "$bridge_url/api/mode"
        set body [::json::write object \
            action [::json::write string "set"] \
            channel [::json::write string $channel] \
            mode [::json::write string $mode]]
        if {[catch {
            set token [::http::geturl $url -method POST \
                -type "application/json" -query $body -timeout 10000]
            set data [::http::data $token]
            ::http::cleanup $token
            return [::json::json2dict $data]
        } err]} {
            return "Error: $err"
        }
    }

    # Grok command handler
    proc pub_grok {nick uhost handle channel text} {
        set hostmask "${nick}!${uhost}"
        if {![check_rate $hostmask]} {
            putserv "PRIVMSG $channel :$nick: Rate limit exceeded."
            return 0
        }
        set clean [sanitize $text]
        if {$clean eq ""} {
            putserv "PRIVMSG $channel :$nick: Empty message."
            return 0
        }
        putserv "PRIVMSG $channel :$nick: Thinking..."
        set answer [bridge_chat $channel $nick $clean]
        set answer [string map {"\n" " | "} $answer]
        # Split long messages
        set maxlen 400
        set len [string length $answer]
        for {set i 0} {$i < $len} {incr i $maxlen} {
            set chunk [string range $answer $i [expr {$i + $maxlen - 1}]]
            putserv "PRIVMSG $channel :$nick: $chunk"
        }
        return 0
    }

    # Admin command handler
    proc pub_admin {nick uhost handle channel text} {
        # Check eggdrop flags - require owner (n) or master (m)
        if {![matchattr $handle n|n $channel] && ![matchattr $handle m|m $channel]} {
            putserv "PRIVMSG $channel :$nick: Permission denied."
            return 0
        }

        set parts [split $text]
        set action [string tolower [lindex $parts 0]]

        switch $action {
            "setmode" {
                if {[llength $parts] >= 2} {
                    set mode [lindex $parts 1]
                    set result [bridge_set_mode $channel $mode]
                    putserv "PRIVMSG $channel :$nick: Mode: $result"
                }
            }
            "status" {
                variable bridge_url
                if {[catch {
                    set token [::http::geturl "$bridge_url/api/status" -timeout 5000]
                    set data [::http::data $token]
                    ::http::cleanup $token
                    putserv "PRIVMSG $channel :$nick: $data"
                } err]} {
                    putserv "PRIVMSG $channel :$nick: Bridge unavailable"
                }
            }
            "help" {
                putserv "PRIVMSG $channel :Admin: setmode <mode>, status, help"
            }
            default {
                putserv "PRIVMSG $channel :$nick: Unknown command. Try: !admin help"
            }
        }
        return 0
    }

    # Help handler
    proc pub_help {nick uhost handle channel text} {
        putserv "PRIVMSG $channel :groc-IRC: !grok <question> | !admin <cmd> | !help"
        return 0
    }
}

# Bind commands
bind pub - !grok ::grocbot_egg::pub_grok
bind pub - !admin ::grocbot_egg::pub_admin
bind pub - !help ::grocbot_egg::pub_help

putlog "groc-IRC Eggdrop script loaded."
