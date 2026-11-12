"""Anime4K's CNN x2 (S) upscaler as shader model 3.0 pixel shaders: anime4k_x2_s.hlsl beside this file is written by
this script from Anime4K's own mpv shader, so its weights are that file's, number for number.

    python3 generate.py Anime4K_Upscale_CNN_x2_S.glsl anime4k_x2_s.hlsl

The source: https://github.com/bloc97/Anime4K, glsl/Upscale/Anime4K_Upscale_CNN_x2_S.glsl as of commit
28535a4aff3deb55707a36c2f2d05009e0cb7fb3 (SHA-256 4c53ec2e287908f7ee7bcb266b0170421626d663576468b7d7dafc62962649a4),
MIT License (LICENSE.txt here). Each of its //!DESC passes is a 3x3 convolution: a sum of mat4 * vec4 terms over the
texels around the pixel (the picture's own colour for the first layer; the earlier layer's four features split into
their positive and negative halves, CReLU, for the others), plus a bias. GLSL's mat4(list) * v is HLSL's
mul(v, float4x4(list)): both read the list as GLSL's columns. Its last pass puts each feature texel's four values on the
2x2 pixels it covers at twice the size (depth to space) and adds them, the same to red, green and blue, to the picture
enlarged bilinearly.
"""
import re
import sys


def parse(text):
    """The file's passes: each a dict of its description, the textures it binds, the one it saves, its inputs
    (go_N: texture and the half it takes), its terms (weights, input, x and y offset) and its bias."""
    passes = []
    for block in text.split("//!DESC ")[1:]:
        p = {"desc": block.splitlines()[0].strip(), "binds": re.findall(r"//!BIND (\S+)", block),
             "save": (re.findall(r"//!SAVE (\S+)", block) or [None])[0], "inputs": {}, "terms": [], "bias": None}
        # go_N(x_off, y_off): the texture read at that offset, as it is (0) or its positive (1) or negative (-1) half.
        for n, rest in re.findall(r"#define go_(\d+)\(x_off, y_off\) \((.*)\)\s*$", block, re.M):
            texture = re.search(r"(\w+)_texOff", rest).group(1)
            half = 1 if rest.startswith("max((") else -1 if rest.startswith("max(-(") else 0
            p["inputs"][int(n)] = (texture, half)
        # Each term: sixteen weights, the input it multiplies and that input's offset in texels.
        for weights, n, dx, dy in re.findall(r"mat4\(([^)]*)\) \* go_(\d+)\(([-\d.]+), ([-\d.]+)\)", block):
            values = [w.strip() for w in weights.split(",")]
            # A matrix is sixteen numbers, never fewer (a pattern that matched less would be a misreading).
            assert len(values) == 16
            p["terms"].append((values, int(n), dx, dy))
        bias = re.search(r"result \+= vec4\(([^)]*)\);", block)
        if bias:
            p["bias"] = [b.strip() for b in bias.group(1).split(",")]
        passes.append(p)
    return passes


def check(passes):
    """The shape this script writes for: four layers, the first a 3x3 of the frame (9 terms), each other one a 3x3 of
    the layer just before it, both halves (18 terms), bound by that layer's name; then a last pass onto the picture.
    Another variant (M, L, VL: more or wider layers, or a layer reading several before it) or another file stops here,
    never written wrong."""
    layers = [p for p in passes if p["save"] and p["save"] != "MAIN"]
    if len(layers) != 4 or len(passes) != 5:
        raise SystemExit("not the S model's shape: %d layers in %d passes (4 in 5 written for)" % (len(layers),
                                                                                               len(passes)))
    for k, p in enumerate(layers):
        # What it reads: the frame for the first, the layer before for the others (its name bound and read).
        want = "MAIN" if k == 0 else layers[k - 1]["save"]
        read = {texture for texture, _ in p["inputs"].values()}
        if read != {want} or (k and want not in p["binds"]):
            raise SystemExit("layer %d reads %s, not %s alone" % (k, sorted(read), want))
        # How many terms: nine texels, once (the frame) or in two halves (a layer's features, CReLU).
        if len(p["terms"]) != (9 if k == 0 else 18) or p["bias"] is None:
            raise SystemExit("layer %d has %d terms and %s bias (9 or 18 and one written for)" % (
                k, len(p["terms"]), "a" if p["bias"] is not None else "no"))


def hlsl_number(text):
    """A GLSL number as HLSL takes it: a float literal with a decimal point or an exponent."""
    return text if ("." in text or "e" in text or "E" in text) else text + ".0"


def write(source, out):
    text = open(source, encoding="utf-8").read()
    passes = parse(text)
    # Only the shape the shaders below are written for.
    check(passes)
    # The file's own licence header (its comment lines before the first pass), kept word for word.
    head = text.split("//!DESC")[0].strip().splitlines()
    header = [line[3:] if line.startswith("// ") else "" for line in head]
    lines = ["/*",
             " * Anime4K's CNN x2 upscaler, its small variant (S), as shader model 3.0 pixel shaders for openDMT3's",
             " * post-process chain (post.c): written by generate.py from Anime4K_Upscale_CNN_x2_S.glsl, its weights",
             " * as they are there. Each layer reads the one before point-sampled at whole texels and writes four",
             " * signed features (a half-float target); ps_a4k_out writes the picture at twice the size.",
             " * The file's licence:", " *"]
    lines += [(" * " + line).rstrip() for line in header]
    lines += [" */", "",
              "/* c0 the input's size (w, h, 1/w, 1/h), c1 the output's; s0 the game's frame, s1 the layer before. */",
              "float4 c_in : register(c0);", "float4 c_out : register(c1);",
              "sampler2D s0 : register(s0);", "sampler2D s1 : register(s1);", ""]
    layers = [p for p in passes if p["save"] and p["save"] != "MAIN"]
    for k, p in enumerate(layers):
        lines.append("/* %s. */" % p["desc"])
        lines.append("float4 ps_a4k_%d(float2 vpos : VPOS) : COLOR" % k)
        lines.append("{")
        # The texel's centre (VPOS is its corner on Direct3D 9).
        lines.append("    float2 p = floor(vpos) + 0.5;")
        lines.append("    float4 r = float4(%s);" % ", ".join(hlsl_number(b) for b in p["bias"]))
        reads = {}
        for weights, n, dx, dy in p["terms"]:
            texture, half = p["inputs"][n]
            # The first layer reads the frame (s0), every other one the layer before (s1); each texel read once.
            key = (texture, dx, dy)
            if key not in reads:
                reads[key] = "t%d" % len(reads)
                lines.append("    float4 %s = tex2Dlod(%s, float4((p + float2(%s, %s)) * c_in.zw, 0.0, 0.0));" % (
                    reads[key], "s0" if texture == "MAIN" else "s1", hlsl_number(dx), hlsl_number(dy)))
            v = reads[key]
            arg = v if half == 0 else "max(%s, 0.0)" % v if half == 1 else "max(-%s, 0.0)" % v
            # The matrix a row of four numbers a line, so no line runs past 120 characters.
            rows = [", ".join(hlsl_number(w) for w in weights[i:i + 4]) for i in range(0, 16, 4)]
            lead = "    r += mul(%s, float4x4(" % arg
            lines.append(lead + rows[0] + ",")
            lines += [" " * len(lead) + row + ("," if i < 3 else "));") for i, row in enumerate(rows[1:], 1)]
        lines.append("    return r;")
        lines.append("}")
        lines.append("")
    lines += [
        "/* Depth to space: the last layer's four values a texel are its 2x2 pixels at twice the size (top left, top",
        " * right, bottom left, bottom right), the same residual on red, green and blue over the frame enlarged",
        " * bilinearly (s0 linear). c0 the layers' size, c1 the output's (twice it). */",
        "float4 ps_a4k_out(float2 vpos : VPOS) : COLOR",
        "{",
        "    float2 q = floor(vpos) + 0.5;",
        "    float2 cell = floor(q * 0.5);",
        "    float2 sub = q * 0.5 - cell;",
        "    float4 f = tex2Dlod(s1, float4((cell + 0.5) * c_in.zw, 0.0, 0.0));",
        "    float c = sub.y < 0.5 ? (sub.x < 0.5 ? f.x : f.y) : (sub.x < 0.5 ? f.z : f.w);",
        "    float3 base = tex2Dlod(s0, float4(q * c_out.zw, 0.0, 0.0)).rgb;",
        "    return float4(saturate(base + c), 1.0);",
        "}",
    ]
    open(out, "w", encoding="utf-8", newline="\n").write("\n".join(lines) + "\n")


if __name__ == "__main__":
    write(sys.argv[1], sys.argv[2])
