import { nodeLabel, toolVerb } from "./labels";
import { plainToolArg } from "./ToolChip";

describe("plain activity labels", () => {
  it("names a lookup by what it did", () => {
    expect(toolVerb("get_decision_case")).toBe("Read the decision");
    expect(toolVerb("get_water_status")).toBe("Checked water status");
    expect(toolVerb("get_something_new")).toBe("Get something new");
  });
  it("names a graph node, specialist workers included, without its id", () => {
    expect(nodeLabel("load_context")).toBe("Read the question");
    expect(nodeLabel("worker:water")).toBe("Water analyst looks things up");
    expect(nodeLabel("some_new_node")).toBe("Some new node");
  });
  it("shows a search phrase but never an identifier", () => {
    expect(plainToolArg({ query: "hospital water supply" })).toBe("hospital water supply");
    expect(plainToolArg({ decision_case_id: "DC-D3-HSP-TALLOWBRANCH-WATER" })).toBe("");
  });
});
