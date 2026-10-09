// A stand-in for three.js's SimplexNoise in GTAOPass, written for this
// repository (see ../../README.md): GTAOPass only needs a fixed field of
// values in [-1, 1] to rotate its samples, so a hash of the coordinates does.
export class HashNoise {

	noise( x, y ) {

		let h = Math.imul( Math.floor( x ) | 0, 374761393 ) ^ Math.imul( Math.floor( y ) | 0, 668265263 );
		h = Math.imul( h ^ ( h >>> 13 ), 1274126177 );
		h ^= h >>> 16;
		return ( ( h >>> 0 ) / 4294967295 ) * 2 - 1;

	}

}
