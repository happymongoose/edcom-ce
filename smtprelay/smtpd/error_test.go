package smtpd

import (
	"bufio"
	"bytes"
	"errors"
	"fmt"
	"net"
	"strings"
	"testing"
)

func TestErrorCodesPreserved(t *testing.T) {
	for _, c := range []struct {
		name string
		err  error
		code string
	}{
		{"value", Error{Code: 451, Message: "temporary"}, "451"},
		{"pointer", &Error{Code: 451, Message: "temporary"}, "451"},
		{"wrapped pointer", fmt.Errorf("wrapped: %w", &Error{Code: 451, Message: "temporary"}), "451"},
		{"wrapped value", fmt.Errorf("wrapped: %w", Error{Code: 550, Message: "permanent"}), "550"},
		{"generic", errors.New("generic"), "502"},
	} {
		t.Run(c.name, func(t *testing.T) {
			conn, other := net.Pipe()
			defer conn.Close()
			defer other.Close()
			var out bytes.Buffer
			s := &session{server: &Server{}, conn: conn, writer: bufio.NewWriter(&out)}
			s.error(c.err)
			if !strings.HasPrefix(out.String(), c.code+" ") {
				t.Fatalf("unexpected reply: %q", out.String())
			}
		})
	}
}
