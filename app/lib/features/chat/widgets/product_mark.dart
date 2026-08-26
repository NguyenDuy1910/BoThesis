import 'package:flutter/material.dart';

import '../../../app/app_theme.dart';

class ProductMark extends StatelessWidget {
  const ProductMark({super.key, this.size = 32});

  final double size;

  @override
  Widget build(BuildContext context) {
    return Semantics(
      label: 'BoThesis',
      image: true,
      child: Container(
        width: size,
        height: size,
        decoration: BoxDecoration(
          color: context.colors.brand,
          borderRadius: BorderRadius.circular(size * 0.26),
          border: Border.all(color: Colors.white.withValues(alpha: 0.18)),
        ),
        alignment: Alignment.center,
        child: Icon(
          Icons.menu_book_rounded,
          color: context.colors.onBrand,
          size: size * 0.52,
        ),
      ),
    );
  }
}
