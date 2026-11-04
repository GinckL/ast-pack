package ledger

import (
	"errors"
	"sync"
)

// ErrNegative is returned for negative amounts.
var ErrNegative = errors.New("negative amount")

const (
	KindDebit = iota
	KindCredit
)

// Entry is one ledger line.
type Entry struct {
	Account string
	Amount  int64
	Kind    int
}

// Ledger stores entries.
type Ledger struct {
	mu      sync.Mutex
	entries []Entry
}

// Append adds an entry after validation.
func (l *Ledger) Append(e Entry) error {
	if err := validate(e); err != nil {
		return err
	}
	l.mu.Lock()
	defer l.mu.Unlock()
	l.entries = append(l.entries, e)
	return nil
}

// Balance sums an account.
func (l *Ledger) Balance(account string) int64 {
	var total int64
	for _, e := range l.entries {
		if e.Account == account {
			total += sign(e.Kind) * e.Amount
		}
	}
	return total
}

func validate(e Entry) error {
	if e.Amount < 0 {
		return ErrNegative
	}
	return nil
}

func sign(kind int) int64 {
	if kind == KindDebit {
		return -1
	}
	return 1
}
