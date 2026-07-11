import { Container, getContainer } from "@cloudflare/containers";

export class WhaleBotContainer extends Container {
  defaultPort = 8080;
  // keep the bot alive between dashboard visits; it still sleeps eventually —
  // see the caveats in wrangler.jsonc
  sleepAfter = "15m";
}

export default {
  async fetch(request, env) {
    return getContainer(env.WHALEBOT).fetch(request);
  },
};
