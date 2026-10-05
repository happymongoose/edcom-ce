package main

import "testing"

func TestMIMECompatibility(t *testing.T) {
	cases := []struct {
		name, body, kind, encoding, want string
		invalid                          bool
	}{
		{"utf8", "Hello £", "text/plain; charset=utf-8", "", "Hello £", false},
		{"latin1", "caf=e9", "text/plain; charset=iso-8859-1", "quoted-printable", "café", false},
		{"base64", "PGI+aGVsbG88L2I+", "text/html", "base64", "<b>hello</b>", false},
		{"multipart", "--x\r\nContent-Type: text/plain\r\n\r\nplain\r\n--x\r\nContent-Type: text/html\r\n\r\n<b>html</b>\r\n--x--\r\n", "multipart/alternative; boundary=x", "", "<b>html</b>", false},
		{"invalid utf8", string([]byte{255}), "text/plain; charset=utf-8", "", "", true},
		{"invalid base64", "!bad", "text/plain", "base64", "", true},
		{"invalid charset", "text", "text/plain; charset=not-a-charset", "", "", true},
		{"encoded multipart", "data", "multipart/alternative; boundary=x", "base64", "", true},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			got, err := extractBody([]byte(c.body), c.kind, c.encoding)
			if (err != nil) != c.invalid || (!c.invalid && got != c.want) {
				t.Fatalf("got %q, %v; want %q invalid=%v", got, err, c.want, c.invalid)
			}
		})
	}
}
