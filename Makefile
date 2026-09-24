BINARY  := orca
VERSION := $(shell grep 'const Version' internal/version/version.go | cut -d'"' -f2)
LDFLAGS := -s -w
TARGETS := linux/amd64 linux/arm64 darwin/amd64 darwin/arm64 windows/amd64

.PHONY: build test race vet fmt clean release install

build:
	CGO_ENABLED=0 go build -trimpath -ldflags="$(LDFLAGS)" -o $(BINARY) ./cmd/orca

test:
	go test -count=1 ./...

race:
	go test -race -count=1 ./...

vet:
	go vet ./...

fmt:
	gofmt -w .

install:
	go install -trimpath -ldflags="$(LDFLAGS)" ./cmd/orca

release: clean
	@mkdir -p dist
	@for t in $(TARGETS); do \
		GOOS=$${t%/*} GOARCH=$${t#*/} CGO_ENABLED=0 \
		go build -trimpath -ldflags="$(LDFLAGS)" \
		-o dist/$(BINARY)-$${t%/*}-$${t#*/}$$([ $${t%/*} = windows ] && echo .exe) ./cmd/orca; \
		echo "built dist/$(BINARY)-$${t%/*}-$${t#*/}"; \
	done

clean:
	rm -rf $(BINARY) $(BINARY).exe dist
