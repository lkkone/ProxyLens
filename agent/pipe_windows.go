//go:build windows

package main

import (
	"context"
	winio "github.com/Microsoft/go-winio"
	"net"
)

func dialPipe(ctx context.Context, path string) (net.Conn, error) {
	return winio.DialPipeContext(ctx, path)
}
