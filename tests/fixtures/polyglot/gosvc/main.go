package main

import (
	"fmt"
	"os"

	"example.com/gosvc/internal/ledger"
)

func transfer(l *ledger.Ledger, from, to string, amount int64) error {
	if err := l.Append(ledger.Entry{Account: from, Amount: amount, Kind: ledger.KindDebit}); err != nil {
		return err
	}
	return l.Append(ledger.Entry{Account: to, Amount: amount, Kind: ledger.KindCredit})
}

func main() {
	l := &ledger.Ledger{}
	if err := transfer(l, "alice", "bob", 100); err != nil {
		fmt.Println(err)
		os.Exit(1)
	}
	fmt.Println(l.Balance("bob"))
}

func usage() string {
	return "gosvc transfer FROM TO AMOUNT"
}
