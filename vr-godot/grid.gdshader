shader_type spatial;
render_mode unshaded, cull_disabled;

// 1 m grid in world space; thicker line every 1 m, faint line every 0.25 m.
uniform vec4 bg_color : source_color = vec4(0.13, 0.14, 0.16, 1.0);
uniform vec4 line_color : source_color = vec4(0.55, 0.58, 0.62, 1.0);
uniform vec4 sub_color : source_color = vec4(0.22, 0.23, 0.26, 1.0);

varying vec3 wpos;

float grid(vec2 p, float cell) {
	vec2 g = abs(fract(p / cell - 0.5) - 0.5) / fwidth(p / cell);
	return 1.0 - min(min(g.x, g.y), 1.0);
}

void vertex() {
	wpos = (MODEL_MATRIX * vec4(VERTEX, 1.0)).xyz;
}

void fragment() {
	float major = grid(wpos.xz, 1.0);
	float minor = grid(wpos.xz, 0.25);
	vec3 c = mix(bg_color.rgb, sub_color.rgb, minor);
	c = mix(c, line_color.rgb, major);
	ALBEDO = c;
}
