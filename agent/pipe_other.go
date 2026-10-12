//go:build !windows

package main

import (
	"context"
	"errors"
	"net"
)

func dialPipe(context.Context, string) (net.Conn, error) {
	return nil, errors.New("命名管道仅支持 Windows")
}
