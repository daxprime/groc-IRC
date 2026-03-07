#!/usr/bin/env tclsh
# groc-IRC Standalone Tcl Bot - Connects to Undernet and talks to Grok via bridge

package require Tcl 8.6
package require http
package require tls
package require json

namespace eval ::grocbot {
    # Configuration
    variable config
    array set config {
        server      "us.undernet.org"
        port        6667
        nickname    "GrocTcl"
        username    "groctcl"
        realname    "Grok Tcl IRC Bot"
        channels    "#grocbot"
        bridge_url  "http://127.0.0.1:5580"
        prefix      "!"
        admin_host  "*!*@*"
        managers    {}
        rate_limit  5
        rate_window 60
        encoding    "utf-8"
    }

    variable sock ""
    variable connected 0
    variable rate_data
    array set rate_data {}

    # Load config from file if exists
    proc load_config {file} {
        variable config
        if {[file exists $file]} {
            set fd [open $file r]
            set data [read $fd]
            close $fd
            if {[catch {set parsed [::json::json2dict $data]} err]} {
                puts "Config parse error: $err"
                return
            }
            if {[dict exists $parsed irc]} {
                set irc [dict get $parsed irc]
                foreach key {server port nickname username realname} {
                    if {[dict exists $irc $key]} {
                        set config($key) [dict get $irc $key]
                    }
                }
                if {[dict exists $irc channels]} {
                    set config(channels) [join [dict get $irc channels] ","]
                }
            }
        }
    }

    # Rate limiting
    proc check_rate {hostmask} {
        variable rate_data
        variable config
        set now [clock seconds]
        set window $config(rate_window)
        set max $config(rate_limit)

        if {![info exists rate_data($hostmask)]} {
            set rate_data($hostmask) [list $now]
            return 1
        }

        set times {}
        foreach t $rate_data($hostmask) {
            if {$now - $t < $window} {
                lappend times $t
            }
        }
        if {[llength $times] >= $max} {
            set rate_data($hostmask) $times
            return 0
        }
        lappend times $now
        set rate_data($hostmask) $times
        return 1
    }

    # Input sanitization
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

    # Admin check
    proc is_admin {hostmask} {
        variable config
        if {[string match -nocase $config(admin_host) $hostmask]} {
            return 1
        }
        foreach mgr $config(managers) {
            if {[string match -nocase $mgr $hostmask]} {
                return 1
            }
        }
        return 0
    }

    # Bridge API call
    proc bridge_chat {channel user message} {
        variable config
        set url "$config(bridge_url)/api/chat"
        set body [::json::write object \
            channel [::json::write string $channel] \
            user [::json::write string $user] \
            message [::json::write string $message]]

        if {[catch {
            set token [::http::geturl $url -method POST \
                -type "application/json" \
                -query $body -timeout 30000]
            set status [::http::status $token]
            set data [::http::data $token]
            ::http::cleanup $token

            if {$status eq "ok"} {
                set parsed [::json::json2dict $data]
                if {[dict exists $parsed content]} {
                    return [dict get $parsed content]
                }
                if {[dict exists $parsed error]} {
                    return "Error: [dict get $parsed error]"
                }
            }
            return "Bridge error: $status"
        } err]} {
            return "Bridge connection error: $err"
        }
    }

    # Bridge mode control
    proc bridge_set_mode {channel mode} {
        variable config
        set url "$config(bridge_url)/api/mode"
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

    # IRC send
    proc send {msg} {
        variable sock
        if {$sock ne ""} {
            puts $sock $msg
            flush $sock
        }
    }

    proc send_msg {target text} {
        set maxlen 400
        set len [string length $text]
        for {set i 0} {$i < $len} {incr i $maxlen} {
            set chunk [string range $text $i [expr {$i + $maxlen - 1}]]
            send "PRIVMSG $target :$chunk"
            after 500
        }
    }

    # Parse IRC message
    proc parse_line {line} {
        set prefix ""
        set nick ""
        set user ""
        set host ""
        set rest $line

        if {[string index $line 0] eq ":"} {
            set idx [string first " " $line]
            set prefix [string range $line 1 [expr {$idx - 1}]]
            set rest [string range $line [expr {$idx + 1}] end]

            if {[regexp {^([^!]+)!([^@]+)@(.+)$} $prefix -> n u h]} {
                set nick $n; set user $u; set host $h
            } else {
                set nick $prefix
            }
        }

        set parts [split $rest]
        set command [lindex $parts 0]
        set params [lrange $parts 1 end]

        set trailing ""
        set trail_idx [string first " :" $rest]
        if {$trail_idx >= 0} {
            set trailing [string range $rest [expr {$trail_idx + 2}] end]
        }

        return [dict create prefix $prefix nick $nick user $user host $host \
            command $command params $params trailing $trailing \
            hostmask "${nick}!${user}@${host}"]
    }

    # Handle incoming
    proc handle_line {line} {
        variable config

        if {[string match "PING *" $line]} {
            set token [string range $line 5 end]
            send "PONG :$token"
            return
        }

        set msg [parse_line $line]
        set cmd [dict get $msg command]
        set nick [dict get $msg nick]
        set hostmask [dict get $msg hostmask]

        if {$cmd eq "001"} {
            puts "Connected to server"
            foreach ch [split $config(channels) ","] {
                set ch [string trim $ch]
                if {$ch ne ""} { send "JOIN $ch" }
            }
            return
        }

        if {$cmd eq "433"} {
            append config(nickname) "_"
            send "NICK $config(nickname)"
            return
        }

        if {$cmd ne "PRIVMSG"} return

        set target [lindex [dict get $msg params] 0]
        set text [dict get $msg trailing]

        if {![string match "#*" $target]} return

        set prefix $config(prefix)

        if {[string match "${prefix}grok *" $text]} {
            set question [string range $text [expr {[string length $prefix] + 5}] end]
            if {![check_rate $hostmask]} {
                send_msg $target "$nick: Rate limit exceeded."
                return
            }
            set clean [sanitize $question]
            if {$clean eq ""} {
                send_msg $target "$nick: Empty message."
                return
            }
            send_msg $target "$nick: Thinking..."
            set answer [bridge_chat $target $nick $clean]
            set answer [string map {"\n" " | "} $answer]
            send_msg $target "$nick: $answer"
            return
        }

        if {[string match "${prefix}admin *" $text]} {
            if {![is_admin $hostmask]} {
                send_msg $target "$nick: Permission denied."
                return
            }
            set parts [split [string range $text [expr {[string length $prefix] + 6}] end]]
            set action [lindex $parts 0]

            switch -nocase $action {
                "setmode" {
                    if {[llength $parts] >= 2} {
                        set mode [lindex $parts 1]
                        set result [bridge_set_mode $target $mode]
                        send_msg $target "$nick: Mode result: $result"
                    }
                }
                "addmanager" {
                    if {[llength $parts] >= 2} {
                        set mask [lindex $parts 1]
                        lappend config(managers) $mask
                        send_msg $target "$nick: Manager $mask added."
                    }
                }
                "help" {
                    send_msg $target "Admin: setmode, addmanager, help"
                }
                default {
                    send_msg $target "$nick: Unknown admin command."
                }
            }
            return
        }

        if {$text eq "${prefix}help"} {
            send_msg $target "groc-IRC Tcl Bot: ${prefix}grok <question> | ${prefix}admin <cmd> | ${prefix}help"
        }
    }

    # Read loop
    proc read_handler {} {
        variable sock
        variable connected

        if {[eof $sock]} {
            set connected 0
            puts "Disconnected from server"
            close $sock
            after 30000 [namespace code connect]
            return
        }

        gets $sock line
        if {$line ne ""} {
            handle_line $line
        }
    }

    # Connect
    proc connect {} {
        variable config
        variable sock
        variable connected

        puts "Connecting to $config(server):$config(port)..."
        if {[catch {
            set sock [socket $config(server) $config(port)]
            fconfigure $sock -translation crlf -buffering line -encoding $config(encoding)
            fileevent $sock readable [namespace code read_handler]
            set connected 1
            send "NICK $config(nickname)"
            send "USER $config(username) 0 * :$config(realname)"
            puts "Registration sent."
        } err]} {
            puts "Connection error: $err"
            after 30000 [namespace code connect]
        }
    }

    # Main
    proc main {} {
        load_config "config/settings.json"
        connect
        vwait ::forever
    }
}

::grocbot::main
