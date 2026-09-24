// Command orca is the Orca Code CLI: a secure, zero-dependency terminal
// coding agent shipped as a single static binary.
package main

import (
	"context"
	"flag"
	"fmt"
	"io"
	"os"
	"os/signal"
	"strings"
	"syscall"

	"github.com/Nethyric/orca/internal/agent"
	"github.com/Nethyric/orca/internal/config"
	"github.com/Nethyric/orca/internal/permissions"
	"github.com/Nethyric/orca/internal/provider"
	"github.com/Nethyric/orca/internal/session"
	"github.com/Nethyric/orca/internal/tools"
	"github.com/Nethyric/orca/internal/ui"
	"github.com/Nethyric/orca/internal/version"
)

func main() {
	if err := run(os.Args[1:]); err != nil {
		fmt.Fprintf(os.Stderr, "✗ %v\n", err)
		os.Exit(1)
	}
}

func run(args []string) error {
	// subcommands without flags
	if len(args) > 0 {
		switch args[0] {
		case "version", "--version", "-v":
			fmt.Printf("orca %s\n", version.Version)
			return nil
		case "trust":
			cwd, _ := os.Getwd()
			if err := config.TrustProject(cwd); err != nil {
				return err
			}
			fmt.Printf("✓ trusted: %s (project hooks/verify_command now allowed)\n", cwd)
			return nil
		case "key":
			if len(args) != 3 {
				return fmt.Errorf("usage: orca key <provider> <api-key>")
			}
			if err := config.SaveKey(args[1], args[2]); err != nil {
				return err
			}
			fmt.Printf("✓ key for %s saved to %s/keys.json (0600)\n", args[1], config.Home())
			return nil
		case "help", "--help", "-h":
			usage()
			return nil
		}
	}

	fs := flag.NewFlagSet("orca", flag.ContinueOnError)
	prompt := fs.String("p", "", "one-shot prompt (non-interactive)")
	providerName := fs.String("provider", "", "provider name (anthropic, openai, openrouter, groq, ollama, …)")
	model := fs.String("model", "", "model id")
	mode := fs.String("mode", "", "permission mode: default | acceptEdits | plan | yolo")
	maxCost := fs.Float64("max-cost", 0, "hard session cost cap in USD")
	allowOutside := fs.Bool("allow-outside-root", false, "permit file access outside the project root")
	yes := fs.Bool("yes", false, "with -p: auto-approve permission prompts (like acceptEdits+bash)")
	if err := fs.Parse(args); err != nil {
		return err
	}

	cwd, err := os.Getwd()
	if err != nil {
		return err
	}
	cfg, err := config.Load(cwd)
	if err != nil {
		return err
	}
	if *mode != "" {
		cfg.Mode = *mode
	}
	if *maxCost > 0 {
		cfg.MaxCostUSD = *maxCost
	}
	if *model != "" {
		cfg.Model = *model
	}

	pm, err := permissions.ParseMode(cfg.Mode)
	if err != nil {
		return err
	}
	if *yes && *prompt != "" {
		pm = permissions.Yolo // explicit opt-in for non-interactive runs
	}
	perms := permissions.New(pm, cfg.Allow, cfg.Deny)

	settings, err := cfg.ResolveProvider(*providerName)
	if err != nil {
		return err
	}
	if settings.APIKey == "" && settings.Name != "ollama" {
		return fmt.Errorf("no API key for %q — set %s, or run: orca key %s <key>",
			settings.Name, config.Presets[settings.Name].KeyEnv, settings.Name)
	}
	prov, err := provider.New(settings, nil)
	if err != nil {
		return err
	}

	tc := tools.NewContext(cwd)
	tc.AllowOutsideRoot = *allowOutside
	u := ui.New()
	for _, w := range cfg.Warnings {
		u.Warn(w)
	}
	ag := agent.New(prov, cfg, perms, tc, u, settings.Model)
	if sw, err := session.New(config.Home()); err == nil {
		ag.Session = sw
	}

	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()

	if *prompt != "" {
		_, err := ag.Run(ctx, *prompt)
		return err
	}
	return repl(ctx, ag, u, tc, cfg, settings)
}

func repl(ctx context.Context, ag *agent.Agent, u *ui.UI, tc *tools.Context, cfg *config.Config, settings config.ProviderSettings) error {
	u.Banner(version.Version, settings.Name+"/"+settings.Model, cfg.Root, cfg.Mode)
	if !cfg.Trusted {
		u.Info("project is untrusted: hooks/verify_command from .orca/ are ignored (run `orca trust` to enable)")
	}
	for {
		line, err := u.ReadLine()
		if err != nil {
			if err == io.EOF {
				return nil
			}
			return err
		}
		if line == "" {
			continue
		}
		if strings.HasPrefix(line, "/") {
			if quit := replCommand(line, u, tc, ag); quit {
				return nil
			}
			continue
		}
		if _, err := ag.Run(ctx, line); err != nil {
			u.Error(err.Error())
		}
	}
}

func replCommand(line string, u *ui.UI, tc *tools.Context, ag *agent.Agent) (quit bool) {
	switch strings.Fields(line)[0] {
	case "/quit", "/exit", "/q":
		return true
	case "/undo":
		restored := tc.Undo.UndoLastTurn()
		if len(restored) == 0 {
			u.Info("nothing to undo")
		}
		for _, r := range restored {
			u.Success(r)
		}
	case "/cost":
		u.Meter(ag.TotalIn, ag.TotalOut, ag.TotalCost, ag.Cfg.MaxCostUSD)
	case "/help":
		u.Info("/undo   revert the last turn's file changes")
		u.Info("/cost   show token/cost usage")
		u.Info("/quit   exit")
	default:
		u.Warn("unknown command (try /help)")
	}
	return false
}

func usage() {
	fmt.Print(`orca — secure terminal coding agent (single static binary)

usage:
  orca                          interactive session in the current directory
  orca -p "prompt"              one-shot, non-interactive (asks are denied; add --yes to allow)
  orca trust                    trust this project (enables .orca/ hooks & verify_command)
  orca key <provider> <key>     store an API key (0600)
  orca version

flags:
  --provider NAME   anthropic | openai | openrouter | groq | deepseek | mistral | ollama | …
  --model ID        model id (defaults per provider)
  --mode MODE       default | acceptEdits | plan | yolo
  --max-cost USD    hard session cost cap
  --allow-outside-root   lift project-root file confinement (off by default)
`)
}
