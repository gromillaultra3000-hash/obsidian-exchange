<?php

namespace App\Filament\Resources;

use App\Filament\Resources\LimitOrderResource\Pages;
use App\Models\LimitOrder;
use Filament\Forms;
use Filament\Forms\Form;
use Filament\Tables;
use Filament\Tables\Table;

class LimitOrderResource extends ReadOnlyResource
{
    protected static ?string $model = LimitOrder::class;

    protected static ?string $navigationIcon = 'heroicon-o-flag';

    protected static ?string $navigationLabel = 'Лимитные ордера';

    protected static ?string $modelLabel = 'лимитный ордер';

    protected static ?string $pluralModelLabel = 'лимитные ордера';

    protected static ?string $navigationGroup = 'Торговля';

    protected static ?int $navigationSort = 5;

    public static function form(Form $form): Form
    {
        return $form
            ->schema([
                Forms\Components\TextInput::make('user_id')
                    ->label('User ID')
                    ->numeric()
                    ->disabled(),
                Forms\Components\TextInput::make('currency')
                    ->label('Валюта')
                    ->disabled(),
                Forms\Components\TextInput::make('rub_amount')
                    ->label('Сумма, RUB')
                    ->numeric()
                    ->disabled(),
                Forms\Components\TextInput::make('target_rate')
                    ->label('Целевой курс')
                    ->numeric()
                    ->disabled(),
                Forms\Components\TextInput::make('direction')
                    ->label('Направление')
                    ->disabled(),
                Forms\Components\TextInput::make('payment_method')
                    ->label('Способ оплаты')
                    ->disabled(),
                Forms\Components\TextInput::make('status')
                    ->label('Статус')
                    ->disabled(),
                Forms\Components\TextInput::make('crypto_address')
                    ->label('Крипто адрес')
                    ->disabled()
                    ->columnSpanFull(),
                Forms\Components\TextInput::make('created_at')
                    ->label('Создано')
                    ->disabled(),
                Forms\Components\TextInput::make('expires_at')
                    ->label('Истекает')
                    ->disabled(),
                Forms\Components\TextInput::make('triggered_at')
                    ->label('Сработал')
                    ->disabled(),
                Forms\Components\TextInput::make('order_id')
                    ->label('Order ID')
                    ->numeric()
                    ->disabled(),
            ]);
    }

    public static function table(Table $table): Table
    {
        return $table
            ->defaultSort('id', 'desc')
            ->columns([
                Tables\Columns\TextColumn::make('id')
                    ->label('#')
                    ->sortable(),
                Tables\Columns\TextColumn::make('user_id')
                    ->label('User ID')
                    ->numeric()
                    ->sortable(),
                Tables\Columns\TextColumn::make('currency')
                    ->label('Валюта')
                    ->badge(),
                Tables\Columns\TextColumn::make('rub_amount')
                    ->label('Сумма, RUB')
                    ->numeric(2)
                    ->sortable(),
                Tables\Columns\TextColumn::make('target_rate')
                    ->label('Целевой курс')
                    ->numeric(2)
                    ->sortable(),
                Tables\Columns\TextColumn::make('direction')
                    ->label('Направление')
                    ->badge()
                    ->color(fn (string $state): string => match ($state) {
                        'below' => 'info',
                        'above' => 'warning',
                        default => 'gray',
                    }),
                Tables\Columns\TextColumn::make('payment_method')
                    ->label('Оплата')
                    ->toggleable(),
                Tables\Columns\TextColumn::make('status')
                    ->label('Статус')
                    ->badge()
                    ->color(fn (string $state): string => match ($state) {
                        'active' => 'success',
                        'triggered' => 'info',
                        'expired' => 'warning',
                        'cancelled' => 'danger',
                        default => 'gray',
                    })
                    ->sortable(),
                Tables\Columns\TextColumn::make('expires_at')
                    ->label('Истекает')
                    ->dateTime('d.m.Y H:i')
                    ->sortable()
                    ->toggleable(),
                Tables\Columns\TextColumn::make('created_at')
                    ->label('Создано')
                    ->dateTime('d.m.Y H:i')
                    ->sortable(),
            ])
            ->filters([
                Tables\Filters\SelectFilter::make('status')
                    ->label('Статус')
                    ->options([
                        'active' => 'active',
                        'triggered' => 'triggered',
                        'expired' => 'expired',
                        'cancelled' => 'cancelled',
                    ]),
                Tables\Filters\SelectFilter::make('currency')
                    ->label('Валюта')
                    ->options([
                        'BTC' => 'BTC',
                        'LTC' => 'LTC',
                        'USDT' => 'USDT',
                        'ETH' => 'ETH',
                    ]),
                Tables\Filters\SelectFilter::make('direction')
                    ->label('Направление')
                    ->options([
                        'below' => 'below (купить дешевле)',
                        'above' => 'above (купить дороже)',
                    ]),
            ])
            ->actions([
                Tables\Actions\ViewAction::make(),
            ])
            ->bulkActions([]);
    }

    public static function canCreate(): bool
    {
        return false;
    }

    public static function getPages(): array
    {
        return [
            'index' => Pages\ListLimitOrders::route('/'),
        ];
    }
}
