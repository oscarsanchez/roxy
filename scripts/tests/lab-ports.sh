# Sourced by the tests that run scripts/start-lab, which refuses to start on a busy port:
# they move the lab's ports (scripts/lib.sh) to free ephemeral ports, so a test never looks
# at, or names, the ports of a lab the user is running.

# free_port : a port nothing listens on, from the ephemeral range, never one of the lab's own.
free_port() {
  perl -MIO::Socket::INET -e 'print IO::Socket::INET->new(Listen => 1, LocalAddr => "127.0.0.1", LocalPort => 0)->sockport'
}

# use_test_ports : export every lab port as a free port, in the current shell.
use_test_ports() {
  export LAB_PORT="$(free_port)" LAB_CHARLES_PORT="$(free_port)" LAB_WEB_PORT="$(free_port)" \
    LAB_PROXY_ROUTING_PORT="$(free_port)" LAB_TUNNEL_PORT="$(free_port)" \
    LAB_CA_ROUTING_PORTS="$(free_port) $(free_port)"
}
