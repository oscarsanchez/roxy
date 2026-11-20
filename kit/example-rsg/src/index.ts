import "./compiled-components/BaseAppScene.xml";

import { enableExceptionTagging, main, registerAnchorNode } from "@roku-sdk/rsg-ts";

import ExampleApp from "./components/example-app";

main(() => {
    enableExceptionTagging();
    registerAnchorNode(ExampleApp);
});
