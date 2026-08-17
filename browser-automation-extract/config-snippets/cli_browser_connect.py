    def _handle_browser_command(self, cmd: str):
        """Handle /browser connect|disconnect|status — manage live Chrome CDP connection."""
        import platform as _plat

        parts = cmd.strip().split(None, 1)
        sub = parts[1].lower().strip() if len(parts) > 1 else "status"

        _DEFAULT_CDP = "http://localhost:9222"
        current = os.environ.get("BROWSER_CDP_URL", "").strip()

        if sub.startswith("connect"):
            # Optionally accept a custom CDP URL: /browser connect ws://host:port
            connect_parts = cmd.strip().split(None, 2)  # ["/browser", "connect", "ws://..."]
            cdp_url = connect_parts[2].strip() if len(connect_parts) > 2 else _DEFAULT_CDP

            # Clear any existing browser sessions so the next tool call uses the new backend
            try:
                from tools.browser_tool import cleanup_all_browsers
                cleanup_all_browsers()
            except Exception:
                pass

            print()

            # Extract port for connectivity checks
            _port = 9222
            try:
                _port = int(cdp_url.rsplit(":", 1)[-1].split("/")[0])
            except (ValueError, IndexError):
                pass

            # Check if Chrome is already listening on the debug port
            import socket
            _already_open = False
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(1)
                s.connect(("127.0.0.1", _port))
                s.close()
                _already_open = True
            except (OSError, socket.timeout):
                pass

            if _already_open:
                print(f"   ✓ Chrome is already listening on port {_port}")
            elif cdp_url == _DEFAULT_CDP:
                # Try to auto-launch Chrome with remote debugging
                print("   Chrome isn't running with remote debugging — attempting to launch...")
                _launched = self._try_launch_chrome_debug(_port, _plat.system())
                if _launched:
                    # Wait for the port to come up
                    import time as _time
                    for _wait in range(10):
                        try:
                            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                            s.settimeout(1)
                            s.connect(("127.0.0.1", _port))
                            s.close()
                            _already_open = True
                            break
                        except (OSError, socket.timeout):
                            _time.sleep(0.5)
                    if _already_open:
                        print(f"   ✓ Chrome launched and listening on port {_port}")
                    else:
                        print(f"   ⚠ Chrome launched but port {_port} isn't responding yet")
                        print("     You may need to close existing Chrome windows first and retry")
                else:
                    print("   ⚠ Could not auto-launch Chrome")
                    # Show manual instructions as fallback
                    sys_name = _plat.system()
                    if sys_name == "Darwin":
                        chrome_cmd = 'open -a "Google Chrome" --args --remote-debugging-port=9222'
                    elif sys_name == "Windows":
                        chrome_cmd = 'chrome.exe --remote-debugging-port=9222'
                    else:
                        chrome_cmd = "google-chrome --remote-debugging-port=9222"
                    print(f"     Launch Chrome manually: {chrome_cmd}")
            else:
                print(f"   ⚠ Port {_port} is not reachable at {cdp_url}")

            os.environ["BROWSER_CDP_URL"] = cdp_url
            print()
            print("🌐 Browser connected to live Chrome via CDP")
            print(f"   Endpoint: {cdp_url}")
            print()

            # Inject context message so the model knows
            if hasattr(self, '_pending_input'):
                self._pending_input.put(
                    "[System note: The user has connected your browser tools to their live Chrome browser "
                    "via Chrome DevTools Protocol. Your browser_navigate, browser_snapshot, browser_click, "
                    "and other browser tools now control their real browser — including any pages they have "
                    "open, logged-in sessions, and cookies. They likely opened specific sites or logged into "
                    "services before connecting. Please await their instruction before attempting to operate "
                    "the browser. When you do act, be mindful that your actions affect their real browser — "
                    "don't close tabs or navigate away from pages without asking.]"
                )

        elif sub == "disconnect":
            if current:
                os.environ.pop("BROWSER_CDP_URL", None)
                try:
                    from tools.browser_tool import cleanup_all_browsers
                    cleanup_all_browsers()
                except Exception:
                    pass
                print()
                print("🌐 Browser disconnected from live Chrome")
                print("   Browser tools reverted to default mode (local headless or cloud provider)")
                print()

                if hasattr(self, '_pending_input'):
                    self._pending_input.put(
                        "[System note: The user has disconnected the browser tools from their live Chrome. "
                        "Browser tools are back to default mode (headless local browser or cloud provider).]"
                    )
            else:
                print()
                print("Browser is not connected to live Chrome (already using default mode)")
                print()

        elif sub == "status":
            print()
            if current:
                print("🌐 Browser: connected to live Chrome via CDP")
                print(f"   Endpoint: {current}")

                _port = 9222
                try:
                    _port = int(current.rsplit(":", 1)[-1].split("/")[0])
                except (ValueError, IndexError):
                    pass
                try:
                    import socket
                    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    s.settimeout(1)
                    s.connect(("127.0.0.1", _port))
                    s.close()
                    print("   Status: ✓ reachable")
                except (OSError, Exception):
                    print("   Status: ⚠ not reachable (Chrome may not be running)")
            else:
                try:
                    from tools.browser_tool import _get_cloud_provider
                    provider = _get_cloud_provider()
                except Exception:
                    provider = None

                if provider is not None:
                    print(f"🌐 Browser: {provider.provider_name()} (cloud)")
                else:
                    print("🌐 Browser: local headless Chromium (agent-browser)")
            print()
            print("   /browser connect      — connect to your live Chrome")
            print("   /browser disconnect   — revert to default")
            print()

        else:
            print()
            print("Usage: /browser connect|disconnect|status")
            print()
            print("   connect      Connect browser tools to your live Chrome session")
            print("   disconnect   Revert to default browser backend")
            print("   status       Show current browser mode")
            print()

    def _handle_skin_command(self, cmd: str):
        """Handle /skin [name] — show or change the display skin."""
        try:
            from hermes_cli.skin_engine import list_skins, set_active_skin, get_active_skin_name
        except ImportError:
            print("Skin engine not available.")
            return

        parts = cmd.strip().split(maxsplit=1)
        if len(parts) < 2 or not parts[1].strip():
            # Show current skin and list available
            current = get_active_skin_name()
            skins = list_skins()
